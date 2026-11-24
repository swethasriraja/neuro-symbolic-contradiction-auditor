"""
Unit tests for symbolic solver encodings and no-debate contradiction pipeline.
"""
from __future__ import annotations

from decimal import Decimal
import pytest

from schemas.claim import (
    FinancialClaim,
    FinancialMetric,
    LegalClaim,
    LegalClaimType,
    SourceType,
)
from schemas.finding import FindingStatus
from schemas.pair import CandidatePair
from schemas.solver import SolverOutcome
from schemas.span import SourceSpan
from symbolic.deontic import DeonticSolver
from symbolic.numeric_temporal import NumericTemporalSolver
from symbolic.pipeline import NoDebatePipeline
from symbolic.terms import ScopeStatus, TermResolver

DOC_ID = "c" * 64


def make_span(start: int, end: int, text: str) -> SourceSpan:
    return SourceSpan(
        doc_id=DOC_ID,
        doc_path="doc.txt",
        char_start=start,
        char_end=end,
        text_snippet=text,
    )


class TestNumericTemporalSolver:
    def test_planted_duration_contradiction(self) -> None:
        """Positive: 30 days vs 45 days cure period."""
        text_a = "Licensee shall have thirty (30) days to cure any material breach."
        text_b = "Licensee shall have forty-five (45) days to cure any material breach."

        claim_a = LegalClaim(
            claim_type=LegalClaimType.DEADLINE,
            predicate="cure_period(Licensee, 30, days)",
            raw_text=text_a,
            span=make_span(0, len(text_a), text_a),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )
        claim_b = LegalClaim(
            claim_type=LegalClaimType.DEADLINE,
            predicate="cure_period(Licensee, 45, days)",
            raw_text=text_b,
            span=make_span(100, 100 + len(text_b), text_b),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )

        pair = CandidatePair(claim_a=claim_a, claim_b=claim_b, similarity_score=1.0, retrieval_method="test")
        solver = NumericTemporalSolver()
        res = solver.check_pair(pair)

        assert res.outcome == SolverOutcome.UNSAT
        assert "30 days != 45 days" in (res.temporal_check or "")
        # Unsat core maps claim IDs
        assert claim_a.claim_id in (res.proof_trace or "")
        assert claim_b.claim_id in (res.proof_trace or "")

    def test_planted_payment_precedence_contradiction(self) -> None:
        """Positive: Payment due before invoice is issued."""
        text = "Payment shall be due prior to receipt of invoice."
        claim = LegalClaim(
            claim_type=LegalClaimType.DEADLINE,
            predicate="payment_due(Licensee, before_invoice)",
            raw_text=text,
            span=make_span(0, len(text), text),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )
        pair = CandidatePair(claim_a=claim, claim_b=claim.model_copy(update={"claim_id": "other"}), similarity_score=1.0, retrieval_method="test")
        solver = NumericTemporalSolver()
        res = solver.check_pair(pair)

        assert res.outcome == SolverOutcome.UNSAT
        assert "T_due < T_invoice" in (res.temporal_check or "")

    def test_planted_growth_rate_contradiction(self) -> None:
        """Positive: Narrative states 12% growth, but table numbers show 8%."""
        text_narrative = "Revenue grew 12% in FY2023."
        text_table = "Prior Year: 1000, Current Year: 1080"  # (1080-1000)/1000 = 8%

        claim_narrative = FinancialClaim(
            metric=FinancialMetric.PERCENTAGE,
            value=Decimal("12"),
            unit="%",
            source_type=SourceType.NARRATIVE,
            predicate="revenue_growth(Acme, 12, percent)",
            raw_text=text_narrative,
            span=make_span(0, len(text_narrative), text_narrative),
            confidence=0.95,
            extractor="test",
        )
        claim_table = FinancialClaim(
            metric=FinancialMetric.REVENUE,
            value=Decimal("1080"),
            unit="USD",
            source_type=SourceType.TABLE,
            predicate="revenue(Acme, 1080, USD)",
            raw_text=text_table,
            span=make_span(50, 50 + len(text_table), text_table),
            confidence=0.95,
            extractor="test",
        )

        pair = CandidatePair(claim_a=claim_narrative, claim_b=claim_table, similarity_score=1.0, retrieval_method="test")
        solver = NumericTemporalSolver()
        res = solver.check_pair(pair)

        assert res.outcome == SolverOutcome.UNSAT
        assert "Stated growth 12% != computed 8.00%" in (res.numeric_check or "")

    def test_planted_financial_total_contradiction(self) -> None:
        """Positive: Narrative states $500M vs Table states $520M."""
        text_a = "Total revenue was $500,000,000."
        text_b = "Consolidated Revenue: $520,000,000."

        claim_a = FinancialClaim(
            metric=FinancialMetric.REVENUE,
            value=Decimal("500000000"),
            unit="USD",
            period="FY2023",
            source_type=SourceType.NARRATIVE,
            predicate="revenue(Acme, 500000000, USD)",
            raw_text=text_a,
            span=make_span(0, len(text_a), text_a),
            confidence=0.95,
            extractor="test",
        )
        claim_b = FinancialClaim(
            metric=FinancialMetric.REVENUE,
            value=Decimal("520000000"),
            unit="USD",
            period="FY2023",
            source_type=SourceType.TABLE,
            predicate="revenue(Acme, 520000000, USD)",
            raw_text=text_b,
            span=make_span(50, 50 + len(text_b), text_b),
            confidence=0.95,
            extractor="test",
        )

        pair = CandidatePair(claim_a=claim_a, claim_b=claim_b, similarity_score=1.0, retrieval_method="test")
        solver = NumericTemporalSolver()
        res = solver.check_pair(pair)

        assert res.outcome == SolverOutcome.UNSAT
        assert "500000000 != 520000000" in (res.numeric_check or "")

    def test_false_positive_trap_rounding_within_tolerance(self) -> None:
        """Negative: Narrative states 12% while exact computed is 11.8% (within 0.5% tolerance)."""
        text_a = "Operating margin was approximately 12%."
        text_b = "Operating margin: 11.8%."

        claim_a = FinancialClaim(
            metric=FinancialMetric.PERCENTAGE,
            value=Decimal("12"),
            unit="%",
            source_type=SourceType.NARRATIVE,
            predicate="margin(Acme, 12, percent)",
            raw_text=text_a,
            span=make_span(0, len(text_a), text_a),
            confidence=0.95,
            extractor="test",
        )
        claim_b = FinancialClaim(
            metric=FinancialMetric.PERCENTAGE,
            value=Decimal("11.8"),
            unit="%",
            source_type=SourceType.TABLE,
            predicate="margin(Acme, 11.8, percent)",
            raw_text=text_b,
            span=make_span(50, 50 + len(text_b), text_b),
            confidence=0.95,
            extractor="test",
        )

        pair = CandidatePair(claim_a=claim_a, claim_b=claim_b, similarity_score=1.0, retrieval_method="test")
        solver = NumericTemporalSolver()
        res = solver.check_pair(pair)

        # Within tolerance => SAT (NOT a contradiction!)
        assert res.outcome == SolverOutcome.SAT


class TestDeonticSolver:
    def test_planted_obligation_vs_prohibition(self) -> None:
        """Positive: Licensee shall disclose vs Licensee shall not disclose."""
        text_a = "Licensee shall disclose all confidential audit logs upon request."
        text_b = "Licensee shall not disclose any confidential information to third parties."

        claim_a = LegalClaim(
            claim_type=LegalClaimType.OBLIGATION,
            predicate="obligation_disclose(Licensee)",
            raw_text=text_a,
            span=make_span(0, len(text_a), text_a),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )
        claim_b = LegalClaim(
            claim_type=LegalClaimType.PROHIBITION,
            predicate="prohibition_disclose(Licensee)",
            raw_text=text_b,
            span=make_span(100, 100 + len(text_b), text_b),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )

        pair = CandidatePair(claim_a=claim_a, claim_b=claim_b, similarity_score=1.0, retrieval_method="test")
        solver = DeonticSolver()
        res = solver.check_pair(pair)

        assert res.outcome == SolverOutcome.UNSAT
        assert "DATALOG PROOF TRACE" in (res.proof_trace or "")

    def test_false_positive_trap_amendment_override(self) -> None:
        """Negative: Amendment provision overrides base agreement provision."""
        text_a = "Licensee shall pay an annual license fee of $50,000."
        text_b = "Pursuant to Amendment No. 1, Licensee shall pay an annual license fee of $75,000."

        claim_a = LegalClaim(
            claim_type=LegalClaimType.AMOUNT,
            predicate="fee(Licensee, 50000)",
            raw_text=text_a,
            span=make_span(0, len(text_a), text_a),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )
        claim_b = LegalClaim(
            claim_type=LegalClaimType.AMOUNT,
            predicate="fee(Licensee, 75000)",
            raw_text=text_b,
            span=make_span(100, 100 + len(text_b), text_b),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )

        pair = CandidatePair(claim_a=claim_a, claim_b=claim_b, similarity_score=1.0, retrieval_method="test")
        solver = DeonticSolver()
        res = solver.check_pair(pair)

        # Amendment override => SAT (NOT a contradiction!)
        assert res.outcome == SolverOutcome.SAT


class TestTermsAndScopeResolution:
    def test_business_days_vs_calendar_days(self) -> None:
        """Negative: Disparity between Business Days and calendar days flagged as distinct units."""
        claim_a = LegalClaim(
            claim_type=LegalClaimType.DEADLINE,
            predicate="notice(15, business_days)",
            raw_text="Notice shall be given within fifteen (15) Business Days.",
            span=make_span(0, 10, "dummy"),
            confidence=0.95,
            extractor="test",
        )
        claim_b = LegalClaim(
            claim_type=LegalClaimType.DEADLINE,
            predicate="notice(15, days)",
            raw_text="Notice shall be given within fifteen (15) days.",
            span=make_span(20, 30, "dummy"),
            confidence=0.95,
            extractor="test",
        )

        res = TermResolver.resolve_pair_scope(claim_a, claim_b)
        assert res.status == ScopeStatus.MISMATCHED_UNITS
        assert res.should_audit is False

    def test_conflicting_definitions_resolution(self) -> None:
        """Different definitions for same term => UNRESOLVED."""
        claim_a = LegalClaim(
            claim_type=LegalClaimType.DEFINED_TERM,
            predicate="def(Affiliate)",
            raw_text="Affiliate clause",
            span=make_span(0, 10, "dummy"),
            defined_terms={"Affiliate": "Any entity owning more than 50% voting stock"},
            confidence=0.95,
            extractor="test",
        )
        claim_b = LegalClaim(
            claim_type=LegalClaimType.DEFINED_TERM,
            predicate="def(Affiliate)",
            raw_text="Affiliate clause",
            span=make_span(20, 30, "dummy"),
            defined_terms={"Affiliate": "Any entity with direct operational control"},
            confidence=0.95,
            extractor="test",
        )

        res = TermResolver.resolve_pair_scope(claim_a, claim_b)
        assert res.status == ScopeStatus.CONFLICTING_DEFINITIONS
        assert res.should_audit is False
        assert "conflicting definitions" in (res.reason or "").lower()


class TestNoDebatePipeline:
    def test_end_to_end_positive_contradiction(self) -> None:
        """Full pipeline: 30 days vs 45 days cure period produces FindingStatus.CONTRADICTION."""
        text_a = "Licensee shall have thirty (30) days to cure any material breach."
        text_b = "Licensee shall have forty-five (45) days to cure any material breach."
        doc_text = f"SECTION 1\n{text_a}\n\nSECTION 2\n{text_b}\n"

        start_a = doc_text.index(text_a)
        start_b = doc_text.index(text_b)

        claim_a = LegalClaim(
            claim_type=LegalClaimType.DEADLINE,
            predicate="cure_period(Licensee, 30, days)",
            raw_text=text_a,
            span=make_span(start_a, start_a + len(text_a), text_a),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )
        claim_b = LegalClaim(
            claim_type=LegalClaimType.DEADLINE,
            predicate="cure_period(Licensee, 45, days)",
            raw_text=text_b,
            span=make_span(start_b, start_b + len(text_b), text_b),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )

        pipeline = NoDebatePipeline()
        findings = pipeline.audit_claims([claim_a, claim_b], doc_text)

        assert len(findings) == 1
        f = findings[0]
        assert f.status == FindingStatus.CONTRADICTION
        assert f.spans_verified is True
        assert f.unresolved_flag is False

    def test_pipeline_fabricated_span_becomes_unresolved(self) -> None:
        """Full pipeline: Confirmed logic but invalid span => FindingStatus.UNRESOLVED."""
        text_a = "Licensee shall have thirty (30) days to cure any material breach."
        text_b = "Licensee shall have forty-five (45) days to cure any material breach."
        doc_text = f"SECTION 1\n{text_a}\n\nSECTION 2\n{text_b}\n"

        start_a = doc_text.index(text_a)
        # Fabricate offsets for claim B
        claim_a = LegalClaim(
            claim_type=LegalClaimType.DEADLINE,
            predicate="cure_period(Licensee, 30, days)",
            raw_text=text_a,
            span=make_span(start_a, start_a + len(text_a), text_a),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )
        claim_b = LegalClaim(
            claim_type=LegalClaimType.DEADLINE,
            predicate="cure_period(Licensee, 45, days)",
            raw_text=text_b,
            span=make_span(0, 5, "WRONG TEXT"),  # Fabricated span!
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )

        pipeline = NoDebatePipeline()
        findings = pipeline.audit_claims([claim_a, claim_b], doc_text)

        assert len(findings) == 1
        f = findings[0]
        # Must NOT be CONTRADICTION! Must be UNRESOLVED because span verification failed!
        assert f.status == FindingStatus.UNRESOLVED
        assert f.spans_verified is False
        assert f.unresolved_flag is True
        assert "Span verification failure" in (f.unresolved_reason or "")

    def test_pipeline_determinism(self) -> None:
        """Determinism: Same claims produce identical findings twice."""
        text_a = "Total revenue was $500,000,000."
        text_b = "Consolidated Revenue: $520,000,000."
        doc_text = f"{text_a}\n{text_b}"

        claim_a = FinancialClaim(
            metric=FinancialMetric.REVENUE,
            value=Decimal("500000000"),
            unit="USD",
            period="FY2023",
            source_type=SourceType.NARRATIVE,
            predicate="revenue(Acme, 500000000, USD)",
            raw_text=text_a,
            span=make_span(0, len(text_a), text_a),
            confidence=0.95,
            extractor="test",
        )
        claim_b = FinancialClaim(
            metric=FinancialMetric.REVENUE,
            value=Decimal("520000000"),
            unit="USD",
            period="FY2023",
            source_type=SourceType.TABLE,
            predicate="revenue(Acme, 520000000, USD)",
            raw_text=text_b,
            span=make_span(len(text_a) + 1, len(doc_text), text_b),
            confidence=0.95,
            extractor="test",
        )

        pipeline = NoDebatePipeline()
        run1 = pipeline.audit_claims([claim_a, claim_b], doc_text)
        run2 = pipeline.audit_claims([claim_a, claim_b], doc_text)

        assert len(run1) == len(run2) == 1
        assert run1[0].status == run2[0].status == FindingStatus.CONTRADICTION
        assert run1[0].description == run2[0].description
