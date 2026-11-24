"""
Unit tests for all Step 1 schemas.

Coverage
--------
SourceSpan      — offset validation, snippet length cap
Chunk           — text length, doc_id consistency
LegalClaim      — all 9 claim types, required span, defined terms, scope_qualifier
FinancialClaim  — Decimal exactness, all source types, all metrics
ClaimSet        — module/claim type consistency guard
CandidatePair   — self-pairing rejection, cross-document rejection
DebateMessage   — round bounds, empty claim_ids, full telemetry
DebateThread    — open/closed lifecycle, closed-without-verdict rejection
SolverResult    — UNSATISFIABLE requires proof_trace
Finding         — CONFIRMED invariants (spans_verified + solver_outcome),
                  UNRESOLVED reason requirement, severity cap
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from schemas.span import SourceSpan
from schemas.chunk import Chunk, ChunkType
from schemas.claim import (
    LegalClaim,
    LegalClaimType,
    FinancialClaim,
    FinancialMetric,
    SourceType,
    ClaimModule,
    ClaimSet,
)
from schemas.pair import CandidatePair
from schemas.debate import AgentRole, DebateMessage, DebateThread, ThreadStatus
from schemas.solver import SolverBackend, SolverOutcome, SolverResult
from schemas.finding import Finding, FindingStatus, Severity


# ── Shared constants ────────────────────────────────────────────────────────

DOC_ID_A = "a" * 64   # fake SHA-256 (64 hex chars)
DOC_ID_B = "b" * 64   # different document


# ── Fixture helpers ─────────────────────────────────────────────────────────

def span_data(**overrides: object) -> dict:
    base: dict = {
        "doc_id": DOC_ID_A,
        "doc_path": "contract.pdf",
        "page": 1,
        "section": "§ 4.2",
        "char_start": 0,
        "char_end": 50,
        "text_snippet": "Payment shall be due within thirty (30) days.",
    }
    base.update(overrides)
    return base


def legal_claim_data(**overrides: object) -> dict:
    base: dict = {
        "claim_type": "obligation",
        "predicate": "payment_due(Licensee, 30, days)",
        "raw_text": "Payment shall be due within thirty (30) days.",
        "span": span_data(),
        "confidence": 0.95,
        "extractor": "llm:claude-3-5-sonnet",
    }
    base.update(overrides)
    return base


def financial_claim_data(**overrides: object) -> dict:
    base: dict = {
        "metric": "revenue",
        "value": Decimal("4200000000"),
        "unit": "USD",
        "period": "2023-01-01/2023-12-31",
        "entity": "Apple Inc.",
        "source_type": "table",
        "predicate": "revenue(Apple_Inc, FY2023, 4200000000, USD)",
        "raw_text": "Total revenue was $4.2B for fiscal year 2023.",
        "span": span_data(),
        "confidence": 0.98,
        "extractor": "llm:claude-3-5-sonnet",
    }
    base.update(overrides)
    return base


def solver_result_data(**overrides: object) -> dict:
    base: dict = {
        "pair_id": "pair-123",
        "backend": "z3",
        "outcome": "sat",
        "proof_trace": None,
        "solver_input": "assert payment_days == 30\nassert payment_days == 15",
        "runtime_ms": 42,
    }
    base.update(overrides)
    return base


def debate_message_data(**overrides: object) -> dict:
    base: dict = {
        "thread_id": "thread-123",
        "round_number": 1,
        "sender": "auditor",
        "claim_ids": ["claim-abc"],
        "argument": "These two clauses contradict each other on payment terms.",
        "model": "claude-3-5-sonnet-20241022",
        "prompt_tokens": 1500,
        "completion_tokens": 300,
        "cost_usd": Decimal("0.025"),
        "latency_ms": 1200,
    }
    base.update(overrides)
    return base


def finding_data(**overrides: object) -> dict:
    base: dict = {
        "pair_id": "pair-123",
        "solver_result_id": "sr-456",
        "solver_outcome": "unsat",
        "status": "contradiction",
        "severity": "high",
        "confidence": 0.95,
        "title": "Payment term contradiction",
        "description": "§4.2 states 30 days; §8.1 states 15 days.",
        "claim_a_span": span_data(),
        "claim_b_span": span_data(char_start=100, char_end=150, section="§ 8.1"),
        "spans_verified": True,
        "unresolved_flag": False,
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════════
# SourceSpan tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSourceSpan:
    def test_valid_roundtrip(self) -> None:
        span = SourceSpan(**span_data())
        assert SourceSpan.model_validate_json(span.model_dump_json()) == span

    def test_inverted_offsets(self) -> None:
        with pytest.raises(ValidationError, match="char_end"):
            SourceSpan(**span_data(char_start=50, char_end=10))

    def test_equal_offsets_rejected(self) -> None:
        with pytest.raises(ValidationError, match="char_end"):
            SourceSpan(**span_data(char_start=10, char_end=10))

    def test_negative_start(self) -> None:
        with pytest.raises(ValidationError, match="char_start"):
            SourceSpan(**span_data(char_start=-1, char_end=10))

    def test_snippet_too_long(self) -> None:
        with pytest.raises(ValidationError, match="text_snippet"):
            SourceSpan(**span_data(text_snippet="x" * 501))

    def test_snippet_exactly_500_chars_ok(self) -> None:
        span = SourceSpan(**span_data(text_snippet="x" * 500))
        assert len(span.text_snippet) == 500

    def test_frozen(self) -> None:
        span = SourceSpan(**span_data())
        with pytest.raises(Exception):
            span.char_start = 999  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════
# Chunk tests
# ═══════════════════════════════════════════════════════════════════════════

class TestChunk:
    def test_valid_roundtrip(self) -> None:
        chunk = Chunk(
            doc_id=DOC_ID_A,
            doc_path="contract.pdf",
            text="Payment terms are as follows.",
            span=SourceSpan(**span_data()),
            chunk_type=ChunkType.TEXT,
        )
        assert chunk.chunk_id  # UUID4 generated
        assert Chunk.model_validate_json(chunk.model_dump_json()) == chunk

    def test_text_empty_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Chunk(
                doc_id=DOC_ID_A, doc_path="f.pdf",
                text="",
                span=SourceSpan(**span_data()),
                chunk_type=ChunkType.TEXT,
            )

    def test_text_too_long_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Chunk(
                doc_id=DOC_ID_A, doc_path="f.pdf",
                text="x" * 4097,
                span=SourceSpan(**span_data()),
                chunk_type=ChunkType.TEXT,
            )

    def test_doc_id_mismatch_rejected(self) -> None:
        with pytest.raises(ValidationError, match="doc_id"):
            Chunk(
                doc_id=DOC_ID_B,  # different from span.doc_id (DOC_ID_A)
                doc_path="f.pdf",
                text="Some text.",
                span=SourceSpan(**span_data()),
                chunk_type=ChunkType.TEXT,
            )

    def test_all_chunk_types_accepted(self) -> None:
        for ct in ChunkType:
            chunk = Chunk(
                doc_id=DOC_ID_A, doc_path="f.pdf",
                text="x",
                span=SourceSpan(**span_data()),
                chunk_type=ct,
            )
            assert chunk.chunk_type == ct


# ═══════════════════════════════════════════════════════════════════════════
# LegalClaim tests
# ═══════════════════════════════════════════════════════════════════════════

class TestLegalClaim:
    def test_valid_roundtrip(self) -> None:
        claim = LegalClaim(**legal_claim_data())
        assert claim.claim_id
        assert claim.module == "legal"
        restored = LegalClaim.model_validate_json(claim.model_dump_json())
        assert restored.claim_id == claim.claim_id

    def test_all_nine_claim_types(self) -> None:
        assert len(LegalClaimType) == 9
        for t in LegalClaimType:
            claim = LegalClaim(**legal_claim_data(claim_type=t.value))
            assert claim.claim_type == t

    def test_missing_span_rejected(self) -> None:
        data = legal_claim_data()
        del data["span"]
        with pytest.raises(ValidationError):
            LegalClaim(**data)

    def test_confidence_above_1_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LegalClaim(**legal_claim_data(confidence=1.01))

    def test_confidence_below_0_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LegalClaim(**legal_claim_data(confidence=-0.01))

    def test_defined_terms_stored(self) -> None:
        claim = LegalClaim(**legal_claim_data(
            defined_terms={"Business Day": "Mon–Fri excl. public holidays"}
        ))
        assert claim.defined_terms["Business Day"] == "Mon–Fri excl. public holidays"

    def test_scope_qualifier_stored(self) -> None:
        qualifier = "unless written notice is given 30 days prior"
        claim = LegalClaim(**legal_claim_data(scope_qualifier=qualifier))
        assert claim.scope_qualifier == qualifier

    def test_claim_id_stable(self) -> None:
        fixed_id = "00000000-0000-4000-8000-000000000001"
        claim = LegalClaim(**legal_claim_data(claim_id=fixed_id))
        assert claim.claim_id == fixed_id


# ═══════════════════════════════════════════════════════════════════════════
# FinancialClaim tests
# ═══════════════════════════════════════════════════════════════════════════

class TestFinancialClaim:
    def test_valid_roundtrip(self) -> None:
        claim = FinancialClaim(**financial_claim_data())
        assert claim.module == "financial"
        assert claim.claim_id

    def test_decimal_stored_exactly(self) -> None:
        claim = FinancialClaim(**financial_claim_data(value=Decimal("1234567890.12")))
        assert claim.value == Decimal("1234567890.12")
        assert isinstance(claim.value, Decimal)
        # Ensure no float coercion happened
        assert str(claim.value) == "1234567890.12"

    def test_missing_span_rejected(self) -> None:
        data = financial_claim_data()
        del data["span"]
        with pytest.raises(ValidationError):
            FinancialClaim(**data)

    def test_all_source_types(self) -> None:
        for st in SourceType:
            claim = FinancialClaim(**financial_claim_data(source_type=st.value))
            assert claim.source_type == st

    def test_all_15_metrics(self) -> None:
        assert len(FinancialMetric) == 15
        for m in FinancialMetric:
            claim = FinancialClaim(**financial_claim_data(metric=m.value))
            assert claim.metric == m

    def test_null_value_allowed(self) -> None:
        claim = FinancialClaim(**financial_claim_data(value=None))
        assert claim.value is None

    def test_entity_stored(self) -> None:
        claim = FinancialClaim(**financial_claim_data(entity="EMEA Segment"))
        assert claim.entity == "EMEA Segment"


# ═══════════════════════════════════════════════════════════════════════════
# ClaimSet tests
# ═══════════════════════════════════════════════════════════════════════════

class TestClaimSet:
    def test_legal_claimset_valid(self) -> None:
        c = LegalClaim(**legal_claim_data())
        cs = ClaimSet(
            doc_id=DOC_ID_A, doc_path="f.pdf",
            module=ClaimModule.LEGAL, claims=[c],
        )
        assert cs.set_id

    def test_financial_claimset_valid(self) -> None:
        c = FinancialClaim(**financial_claim_data())
        cs = ClaimSet(
            doc_id=DOC_ID_A, doc_path="f.pdf",
            module=ClaimModule.FINANCIAL, claims=[c],
        )
        assert len(cs.claims) == 1

    def test_financial_claim_in_legal_set_rejected(self) -> None:
        fc = FinancialClaim(**financial_claim_data())
        with pytest.raises(ValidationError, match="LEGAL"):
            ClaimSet(
                doc_id=DOC_ID_A, doc_path="f.pdf",
                module=ClaimModule.LEGAL, claims=[fc],  # type: ignore[list-item]
            )

    def test_legal_claim_in_financial_set_rejected(self) -> None:
        lc = LegalClaim(**legal_claim_data())
        with pytest.raises(ValidationError, match="FINANCIAL"):
            ClaimSet(
                doc_id=DOC_ID_A, doc_path="f.pdf",
                module=ClaimModule.FINANCIAL, claims=[lc],  # type: ignore[list-item]
            )

    def test_empty_claims_allowed(self) -> None:
        cs = ClaimSet(doc_id=DOC_ID_A, doc_path="f.pdf", module=ClaimModule.LEGAL)
        assert cs.claims == []


# ═══════════════════════════════════════════════════════════════════════════
# CandidatePair tests
# ═══════════════════════════════════════════════════════════════════════════

class TestCandidatePair:
    def test_valid_pair(self) -> None:
        ca = LegalClaim(**legal_claim_data())
        cb = LegalClaim(**legal_claim_data())  # new UUID4 each call
        pair = CandidatePair(
            claim_a=ca, claim_b=cb,
            similarity_score=0.92,
            retrieval_method="faiss_cosine",
        )
        assert pair.pair_id
        assert pair.claim_a.claim_id != pair.claim_b.claim_id

    def test_self_pairing_rejected(self) -> None:
        ca = LegalClaim(**legal_claim_data())
        with pytest.raises(ValidationError, match="same claim_id"):
            CandidatePair(
                claim_a=ca, claim_b=ca,
                similarity_score=1.0,
                retrieval_method="faiss_cosine",
            )

    def test_cross_document_pair_rejected(self) -> None:
        ca = LegalClaim(**legal_claim_data())
        cb = LegalClaim(**legal_claim_data(span=span_data(doc_id=DOC_ID_B, doc_path="other.pdf")))
        with pytest.raises(ValidationError, match="intra-document"):
            CandidatePair(
                claim_a=ca, claim_b=cb,
                similarity_score=0.9,
                retrieval_method="faiss_cosine",
            )


# ═══════════════════════════════════════════════════════════════════════════
# DebateMessage tests
# ═══════════════════════════════════════════════════════════════════════════

class TestDebateMessage:
    def test_valid_message(self) -> None:
        msg = DebateMessage(**debate_message_data())
        assert msg.message_id
        assert msg.round_number == 1
        assert msg.sender == AgentRole.AUDITOR

    def test_round_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DebateMessage(**debate_message_data(round_number=0))

    def test_round_four_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DebateMessage(**debate_message_data(round_number=4))

    def test_round_three_accepted(self) -> None:
        msg = DebateMessage(**debate_message_data(round_number=3))
        assert msg.round_number == 3

    def test_empty_claim_ids_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DebateMessage(**debate_message_data(claim_ids=[]))

    def test_telemetry_stored_exactly(self) -> None:
        msg = DebateMessage(**debate_message_data(cost_usd=Decimal("0.123456")))
        assert msg.cost_usd == Decimal("0.123456")
        assert msg.prompt_tokens == 1500
        assert msg.latency_ms == 1200

    def test_all_agent_roles(self) -> None:
        for role in AgentRole:
            msg = DebateMessage(**debate_message_data(sender=role.value))
            assert msg.sender == role


# ═══════════════════════════════════════════════════════════════════════════
# DebateThread tests
# ═══════════════════════════════════════════════════════════════════════════

class TestDebateThread:
    def test_open_thread_valid(self) -> None:
        thread = DebateThread(pair_id="pair-123")
        assert thread.status == ThreadStatus.OPEN
        assert thread.rounds_used == 0
        assert thread.final_verdict is None

    def test_closed_thread_with_verdict_valid(self) -> None:
        sr = SolverResult(**solver_result_data(
            outcome="unsat",
            proof_trace="(unsat-core (p30) (p15))",
        ))
        thread = DebateThread(
            pair_id="pair-123",
            status=ThreadStatus.CLOSED,
            rounds_used=2,
            final_verdict=sr,
        )
        assert thread.final_verdict is not None

    def test_closed_thread_without_verdict_rejected(self) -> None:
        with pytest.raises(ValidationError, match="final_verdict"):
            DebateThread(
                pair_id="pair-123",
                status=ThreadStatus.CLOSED,
                rounds_used=2,
                final_verdict=None,
            )

    def test_timed_out_no_verdict_ok(self) -> None:
        thread = DebateThread(
            pair_id="pair-123",
            status=ThreadStatus.TIMED_OUT,
            rounds_used=3,
        )
        assert thread.final_verdict is None

    def test_rounds_used_cap(self) -> None:
        with pytest.raises(ValidationError):
            DebateThread(pair_id="pair-123", rounds_used=4)


# ═══════════════════════════════════════════════════════════════════════════
# SolverResult tests
# ═══════════════════════════════════════════════════════════════════════════

class TestSolverResult:
    def test_satisfiable_no_trace(self) -> None:
        sr = SolverResult(**solver_result_data(outcome="sat"))
        assert sr.outcome == SolverOutcome.SAT
        assert sr.proof_trace is None

    def test_unsatisfiable_requires_proof_trace(self) -> None:
        with pytest.raises(ValidationError, match="proof_trace"):
            SolverResult(**solver_result_data(outcome="unsat", proof_trace=None))

    def test_unsatisfiable_with_trace_valid(self) -> None:
        sr = SolverResult(**solver_result_data(
            outcome="unsat",
            proof_trace="(unsat-core (payment_days_30) (payment_days_15))",
        ))
        assert sr.proof_trace is not None
        assert sr.outcome == SolverOutcome.UNSAT

    def test_timeout_no_trace_valid(self) -> None:
        sr = SolverResult(**solver_result_data(outcome="unknown"))
        assert sr.outcome == SolverOutcome.UNKNOWN
        assert sr.proof_trace is None

    def test_solver_input_stored(self) -> None:
        encoding = "(declare-const x Int)\n(assert (= x 30))"
        sr = SolverResult(**solver_result_data(solver_input=encoding))
        assert sr.solver_input == encoding

    def test_both_backends_accepted(self) -> None:
        for backend in SolverBackend:
            sr = SolverResult(**solver_result_data(backend=backend.value))
            assert sr.backend == backend


# ═══════════════════════════════════════════════════════════════════════════
# Finding tests
# ═══════════════════════════════════════════════════════════════════════════

class TestFinding:
    def test_confirmed_valid(self) -> None:
        f = Finding(**finding_data())
        assert f.status == FindingStatus.CONTRADICTION
        assert f.spans_verified is True
        assert f.severity == Severity.HIGH

    def test_confirmed_requires_spans_verified(self) -> None:
        with pytest.raises(ValidationError, match="spans_verified"):
            Finding(**finding_data(spans_verified=False))

    def test_confirmed_requires_unsat_outcome(self) -> None:
        with pytest.raises(ValidationError, match="UNSAT"):
            Finding(**finding_data(solver_outcome="sat"))

    def test_unresolved_requires_reason(self) -> None:
        with pytest.raises(ValidationError, match="unresolved_reason"):
            Finding(**finding_data(
                status="unresolved",
                severity="medium",
                solver_outcome="unknown",
                spans_verified=False,
                unresolved_flag=True,
                unresolved_reason=None,
            ))

    def test_unresolved_critical_severity_rejected(self) -> None:
        with pytest.raises(ValidationError, match="UNRESOLVED"):
            Finding(**finding_data(
                status="unresolved",
                severity="critical",
                solver_outcome="unknown",
                spans_verified=False,
                unresolved_flag=True,
                unresolved_reason="Ambiguous clause scope.",
            ))

    def test_unresolved_high_severity_rejected(self) -> None:
        with pytest.raises(ValidationError, match="UNRESOLVED"):
            Finding(**finding_data(
                status="unresolved",
                severity="high",
                solver_outcome="sat",
                spans_verified=False,
                unresolved_flag=True,
                unresolved_reason="Ambiguous entity reference.",
            ))

    def test_unresolved_medium_severity_ok(self) -> None:
        f = Finding(**finding_data(
            status="unresolved",
            severity="medium",
            solver_outcome="unknown",
            spans_verified=False,
            unresolved_flag=True,
            unresolved_reason="Solver timed out; requires human review.",
        ))
        assert f.severity == Severity.MEDIUM
        assert f.unresolved_flag is True

    def test_unresolved_low_severity_ok(self) -> None:
        f = Finding(**finding_data(
            status="unresolved",
            severity="low",
            solver_outcome="unknown",
            spans_verified=False,
            unresolved_flag=True,
            unresolved_reason="Solver internal error.",
        ))
        assert f.severity == Severity.LOW

    def test_consistent_no_flags_ok(self) -> None:
        f = Finding(**finding_data(
            status="consistent",
            severity="info",
            solver_outcome="sat",
            spans_verified=True,
            unresolved_flag=False,
        ))
        assert f.status == FindingStatus.CONSISTENT

    def test_roundtrip_json(self) -> None:
        f = Finding(**finding_data())
        restored = Finding.model_validate_json(f.model_dump_json())
        assert restored.finding_id == f.finding_id
        assert restored.status == f.status
        assert restored.severity == f.severity
