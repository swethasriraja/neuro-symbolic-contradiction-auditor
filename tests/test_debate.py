"""
Unit tests for the bounded multi-agent debate loop and retrieval layer.
Uses MockLLMProvider only — zero external API calls.
"""
from __future__ import annotations

import json
from decimal import Decimal
import pytest

from agents.auditor import AuditorAgent
from agents.debate_loop import DebateLoop
from agents.debate_pipeline import DebateAuditorPipeline
from agents.defender import DefenderAgent
from agents.judge import JudgeAgent
from agents.models import DebateBudget
from agents.verifier import DeterministicVerifier
from extraction.mock_provider import MockLLMProvider
from retrieval.candidate_pairs import HybridCandidatePairGenerator
from retrieval.embedder import LocalEmbedder
from retrieval.faiss_index import FAISSClaimIndex
from schemas.claim import FinancialClaim, FinancialMetric, LegalClaim, LegalClaimType, SourceType
from schemas.finding import FindingStatus
from schemas.pair import CandidatePair
from schemas.span import SourceSpan

DOC_ID = "d" * 64


def make_span(start: int, end: int, text: str) -> SourceSpan:
    return SourceSpan(
        doc_id=DOC_ID,
        doc_path="contract.txt",
        char_start=start,
        char_end=end,
        text_snippet=text,
    )


class TestHybridRetrieval:
    def test_pair_count_well_below_n_squared(self) -> None:
        """Verify that hybrid pair generation stays well below N^2 and respects max cap."""
        # Create 20 synthetic claims
        claims = []
        for i in range(20):
            text = f"Party shall pay license fee of ${1000 + i * 10} annually."
            claims.append(
                LegalClaim(
                    claim_id=f"claim-{i:03d}",
                    claim_type=LegalClaimType.AMOUNT,
                    predicate=f"fee(Licensee, {1000 + i * 10})",
                    raw_text=text,
                    span=make_span(i * 100, i * 100 + len(text), text),
                    parties=["Licensee"],
                    confidence=0.95,
                    extractor="test",
                )
            )

        # N = 20 claims -> N*(N-1)/2 = 190 possible pairs
        embedder = LocalEmbedder(use_mock=True)
        faiss_idx = FAISSClaimIndex(embedder=embedder)
        generator = HybridCandidatePairGenerator(
            faiss_index=faiss_idx,
            top_k=3,
            similarity_threshold=0.70,
            max_candidate_pairs=25,
        )

        pairs = generator.generate_candidate_pairs(claims, apply_cap_for_debate=True)

        # Total pairs must be <= 25 (well below 190!)
        assert len(pairs) <= 25
        assert len(pairs) > 0


class TestDebateLoopWithMock:
    def test_auditor_right_solver_unsat_confirmed(self) -> None:
        """Auditor is right and solver proves UNSAT -> CONTRADICTION."""
        text_a = "Payment shall be due in thirty (30) days."
        text_b = "Payment shall be due in forty-five (45) days."
        doc_text = f"{text_a}\n\n{text_b}"

        claim_a = LegalClaim(
            claim_id="c1",
            claim_type=LegalClaimType.DEADLINE,
            predicate="payment(30, days)",
            raw_text=text_a,
            span=make_span(0, len(text_a), text_a),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )
        claim_b = LegalClaim(
            claim_id="c2",
            claim_type=LegalClaimType.DEADLINE,
            predicate="payment(45, days)",
            raw_text=text_b,
            span=make_span(len(text_a) + 2, len(doc_text), text_b),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )

        pair = CandidatePair(claim_a=claim_a, claim_b=claim_b, similarity_score=0.95, retrieval_method="test")

        # Mock responses
        auditor_resp = {
            "claim_ids": ["c1", "c2"],
            "contradiction_type": "temporal_mismatch",
            "assertion": "30 days contradicts 45 days.",
            "reasoning": "Mutually exclusive deadlines.",
            "cited_snippets": [text_a, text_b],
        }
        defender_resp = {
            "reconciliation_type": "none",
            "explanation": "Clauses are indeed in conflict.",
            "cited_claim_ids": [],
            "reconciliation_basis": "none",
            "supporting_snippet": "",
        }
        judge_resp = {
            "proposed_status": "contradiction",
            "confidence": 0.98,
            "severity": "high",
            "title": "Payment deadline conflict",
            "verdict_summary": "Confirmed contradiction between 30 and 45 days.",
        }

        provider = MockLLMProvider()
        provider.queue_response(json.dumps(auditor_resp))
        provider.queue_response(json.dumps(defender_resp))
        provider.queue_response(json.dumps(judge_resp))

        loop = DebateLoop(
            auditor=AuditorAgent(provider),
            defender=DefenderAgent(provider),
            verifier=DeterministicVerifier(),
            judge=JudgeAgent(provider),
        )

        finding, thread, cost = loop.run_debate(pair, doc_text)

        assert finding.status == FindingStatus.CONTRADICTION
        assert finding.spans_verified is True
        assert finding.judge_overruled is False
        assert thread.rounds_used >= 1

    def test_auditor_wrong_verifier_sat_consistent(self) -> None:
        """Auditor argues contradiction, but solver proves SAT -> CONSISTENT."""
        text_a = "Payment shall be due in thirty (30) days."
        text_b = "Payment shall be due in thirty (30) days."
        doc_text = f"{text_a}\n\n{text_b}"

        claim_a = LegalClaim(
            claim_id="c1",
            claim_type=LegalClaimType.DEADLINE,
            predicate="payment(30, days)",
            raw_text=text_a,
            span=make_span(0, len(text_a), text_a),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )
        claim_b = LegalClaim(
            claim_id="c2",
            claim_type=LegalClaimType.DEADLINE,
            predicate="payment(30, days)",
            raw_text=text_b,
            span=make_span(len(text_a) + 2, len(doc_text), text_b),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )
        pair = CandidatePair(claim_a=claim_a, claim_b=claim_b, similarity_score=1.0, retrieval_method="test")

        auditor_resp = {
            "claim_ids": ["c1", "c2"],
            "contradiction_type": "temporal_mismatch",
            "assertion": "False assertion of contradiction.",
            "reasoning": "Clauses differ in intent.",
            "cited_snippets": [text_a, text_b],
        }
        defender_resp = {
            "reconciliation_type": "none",
            "explanation": "Clauses are identical.",
            "cited_claim_ids": [],
            "reconciliation_basis": "none",
            "supporting_snippet": "",
        }
        judge_resp = {
            "proposed_status": "consistent",
            "confidence": 0.99,
            "severity": "info",
            "title": "Consistent payment terms",
            "verdict_summary": "Both clauses require 30 days.",
        }

        provider = MockLLMProvider()
        provider.queue_response(json.dumps(auditor_resp))
        provider.queue_response(json.dumps(defender_resp))
        provider.queue_response(json.dumps(judge_resp))

        loop = DebateLoop(
            auditor=AuditorAgent(provider),
            defender=DefenderAgent(provider),
            verifier=DeterministicVerifier(),
            judge=JudgeAgent(provider),
        )

        finding, thread, cost = loop.run_debate(pair, doc_text)

        assert finding.status == FindingStatus.CONSISTENT
        assert finding.spans_verified is True

    def test_judge_hallucinates_contradiction_overruled(self) -> None:
        """Judge proposes CONTRADICTION on SAT pair -> overruled to CONSISTENT (Q3 Option B)."""
        text_a = "Payment shall be due in thirty (30) days."
        text_b = "Payment shall be due in thirty (30) days."
        doc_text = f"{text_a}\n\n{text_b}"

        claim_a = LegalClaim(
            claim_id="c1",
            claim_type=LegalClaimType.DEADLINE,
            predicate="payment(30, days)",
            raw_text=text_a,
            span=make_span(0, len(text_a), text_a),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )
        claim_b = LegalClaim(
            claim_id="c2",
            claim_type=LegalClaimType.DEADLINE,
            predicate="payment(30, days)",
            raw_text=text_b,
            span=make_span(len(text_a) + 2, len(doc_text), text_b),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )
        pair = CandidatePair(claim_a=claim_a, claim_b=claim_b, similarity_score=1.0, retrieval_method="test")

        provider = MockLLMProvider()
        provider.queue_response(json.dumps({
            "claim_ids": ["c1", "c2"],
            "contradiction_type": "general",
            "assertion": "I think there's a contradiction.",
            "reasoning": "Subjective disagreement.",
            "cited_snippets": [text_a, text_b],
        }))
        provider.queue_response(json.dumps({
            "reconciliation_type": "none",
            "explanation": "No comment.",
            "cited_claim_ids": [],
            "reconciliation_basis": "none",
            "supporting_snippet": "",
        }))
        # Judge hallucinates CONTRADICTION even though solver is SAT!
        provider.queue_response(json.dumps({
            "proposed_status": "contradiction",
            "confidence": 0.99,
            "severity": "critical",
            "title": "Hallucinated Contradiction",
            "verdict_summary": "I declare this contradictory.",
        }))

        loop = DebateLoop(
            auditor=AuditorAgent(provider),
            defender=DefenderAgent(provider),
            verifier=DeterministicVerifier(),
            judge=JudgeAgent(provider),
        )

        finding, thread, cost = loop.run_debate(pair, doc_text)

        # Code enforcement gate overrules to CONSISTENT!
        assert finding.status == FindingStatus.CONSISTENT
        assert finding.judge_overruled is True
        assert "overruled to CONSISTENT" in (finding.judge_overrule_reason or "")

    def test_auditor_cites_fabricated_span_becomes_unresolved(self) -> None:
        """Auditor cites fabricated span -> cannot be CONTRADICTION -> UNRESOLVED."""
        text_a = "Payment shall be due in thirty (30) days."
        text_b = "Payment shall be due in forty-five (45) days."
        doc_text = f"{text_a}\n\n{text_b}"

        # Fabricated span for claim B
        claim_a = LegalClaim(
            claim_id="c1",
            claim_type=LegalClaimType.DEADLINE,
            predicate="payment(30, days)",
            raw_text=text_a,
            span=make_span(0, len(text_a), text_a),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )
        claim_b = LegalClaim(
            claim_id="c2",
            claim_type=LegalClaimType.DEADLINE,
            predicate="payment(45, days)",
            raw_text=text_b,
            span=make_span(0, 5, "WRONG NONEXISTENT TEXT"),  # Fabricated!
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )
        pair = CandidatePair(claim_a=claim_a, claim_b=claim_b, similarity_score=0.95, retrieval_method="test")

        provider = MockLLMProvider()
        provider.queue_response(json.dumps({
            "claim_ids": ["c1", "c2"],
            "contradiction_type": "temporal_mismatch",
            "assertion": "Deadline contradiction.",
            "reasoning": "30 != 45.",
            "cited_snippets": [text_a, text_b],
        }))
        provider.queue_response(json.dumps({
            "reconciliation_type": "none",
            "explanation": "No defense.",
            "cited_claim_ids": [],
            "reconciliation_basis": "none",
            "supporting_snippet": "",
        }))
        provider.queue_response(json.dumps({
            "proposed_status": "contradiction",
            "confidence": 0.95,
            "severity": "high",
            "title": "Payment deadline conflict",
            "verdict_summary": "Unsat.",
        }))

        loop = DebateLoop(
            auditor=AuditorAgent(provider),
            defender=DefenderAgent(provider),
            verifier=DeterministicVerifier(),
            judge=JudgeAgent(provider),
        )

        finding, thread, cost = loop.run_debate(pair, doc_text)

        # Must NOT be CONTRADICTION because span failed verification -> UNRESOLVED!
        assert finding.status == FindingStatus.UNRESOLVED
        assert finding.spans_verified is False
        assert finding.unresolved_flag is True

    def test_defender_valid_reconciliation_yields_consistent(self) -> None:
        """Defender cites verified contractual exception -> neutralized to CONSISTENT."""
        text_a = "Payment shall be due in thirty (30) days."
        text_b = "Payment shall be due in fifteen (15) days unless prior written notice is provided."
        doc_text = f"{text_a}\n\n{text_b}"

        claim_a = LegalClaim(
            claim_id="c1",
            claim_type=LegalClaimType.DEADLINE,
            predicate="payment(30, days)",
            raw_text=text_a,
            span=make_span(0, len(text_a), text_a),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )
        claim_b = LegalClaim(
            claim_id="c2",
            claim_type=LegalClaimType.DEADLINE,
            predicate="payment(15, days)",
            raw_text=text_b,
            span=make_span(len(text_a) + 2, len(doc_text), text_b),
            parties=["Licensee"],
            scope_qualifier="unless prior written notice is provided",
            confidence=0.95,
            extractor="test",
        )
        pair = CandidatePair(claim_a=claim_a, claim_b=claim_b, similarity_score=0.95, retrieval_method="test")

        provider = MockLLMProvider()
        provider.queue_response(json.dumps({
            "claim_ids": ["c1", "c2"],
            "contradiction_type": "temporal_mismatch",
            "assertion": "30 days vs 15 days.",
            "reasoning": "Deadlines conflict.",
            "cited_snippets": [text_a, text_b],
        }))
        # Defender provides verified conditional exception snippet
        provider.queue_response(json.dumps({
            "reconciliation_type": "scope_exception",
            "explanation": "Clause B contains a conditional exception.",
            "cited_claim_ids": ["c2"],
            "reconciliation_basis": "conditional_clause",
            "supporting_snippet": "unless prior written notice is provided",
        }))
        provider.queue_response(json.dumps({
            "proposed_status": "consistent",
            "confidence": 0.95,
            "severity": "info",
            "title": "Reconciled deadline",
            "verdict_summary": "Clause B is conditioned by prior written notice exception.",
        }))

        loop = DebateLoop(
            auditor=AuditorAgent(provider),
            defender=DefenderAgent(provider),
            verifier=DeterministicVerifier(),
            judge=JudgeAgent(provider),
        )

        finding, thread, cost = loop.run_debate(pair, doc_text)

        assert finding.status == FindingStatus.CONSISTENT

    def test_defender_unsupported_reconciliation_ignored(self) -> None:
        """Defender provides ungrounded/hallucinated snippet -> rejected, contradiction confirmed."""
        text_a = "Payment shall be due in thirty (30) days."
        text_b = "Payment shall be due in forty-five (45) days."
        doc_text = f"{text_a}\n\n{text_b}"

        claim_a = LegalClaim(
            claim_id="c1",
            claim_type=LegalClaimType.DEADLINE,
            predicate="payment(30, days)",
            raw_text=text_a,
            span=make_span(0, len(text_a), text_a),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )
        claim_b = LegalClaim(
            claim_id="c2",
            claim_type=LegalClaimType.DEADLINE,
            predicate="payment(45, days)",
            raw_text=text_b,
            span=make_span(len(text_a) + 2, len(doc_text), text_b),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )
        pair = CandidatePair(claim_a=claim_a, claim_b=claim_b, similarity_score=0.95, retrieval_method="test")

        provider = MockLLMProvider()
        provider.queue_response(json.dumps({
            "claim_ids": ["c1", "c2"],
            "contradiction_type": "temporal_mismatch",
            "assertion": "30 days vs 45 days.",
            "reasoning": "Mutually exclusive.",
            "cited_snippets": [text_a, text_b],
        }))
        # Defender invents a snippet NOT present in doc_text
        provider.queue_response(json.dumps({
            "reconciliation_type": "scope_exception",
            "explanation": "Applies only to special international orders.",
            "cited_claim_ids": ["c2"],
            "reconciliation_basis": "conditional_clause",
            "supporting_snippet": "for international special orders only",
        }))
        provider.queue_response(json.dumps({
            "proposed_status": "contradiction",
            "confidence": 0.95,
            "severity": "high",
            "title": "Payment deadline contradiction",
            "verdict_summary": "Unrefuted contradiction.",
        }))

        loop = DebateLoop(
            auditor=AuditorAgent(provider),
            defender=DefenderAgent(provider),
            verifier=DeterministicVerifier(),
            judge=JudgeAgent(provider),
        )

        finding, thread, cost = loop.run_debate(pair, doc_text)

        # Because the defense snippet was ungrounded, it carried zero weight -> CONTRADICTION!
        assert finding.status == FindingStatus.CONTRADICTION

    def test_budget_limit_enforced(self) -> None:
        """Token/cost budget exceeded -> terminates debate and marks UNRESOLVED."""
        text_a = "Payment shall be due in thirty (30) days."
        text_b = "Payment shall be due in forty-five (45) days."
        doc_text = f"{text_a}\n\n{text_b}"

        claim_a = LegalClaim(
            claim_id="c1",
            claim_type=LegalClaimType.DEADLINE,
            predicate="payment(30, days)",
            raw_text=text_a,
            span=make_span(0, len(text_a), text_a),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )
        claim_b = LegalClaim(
            claim_id="c2",
            claim_type=LegalClaimType.DEADLINE,
            predicate="payment(45, days)",
            raw_text=text_b,
            span=make_span(len(text_a) + 2, len(doc_text), text_b),
            parties=["Licensee"],
            confidence=0.95,
            extractor="test",
        )
        pair = CandidatePair(claim_a=claim_a, claim_b=claim_b, similarity_score=0.95, retrieval_method="test")

        provider = MockLLMProvider()
        # Set tiny budget of $0.000001
        tiny_budget = DebateBudget(
            max_rounds=3,
            per_pair_cost_budget_usd=Decimal("0.0000001"),
        )
        loop = DebateLoop(
            auditor=AuditorAgent(provider),
            defender=DefenderAgent(provider),
            verifier=DeterministicVerifier(),
            judge=JudgeAgent(provider),
            budget=tiny_budget,
        )

        # Simulate non-zero cost
        provider.queue_response(json.dumps({
            "claim_ids": ["c1", "c2"],
            "contradiction_type": "general",
            "assertion": "test",
            "reasoning": "test",
            "cited_snippets": [text_a, text_b],
        }))
        provider.call_history.append({"cost_usd": Decimal("1.00")})

        finding, thread, cost = loop.run_debate(pair, doc_text, doc_cumulative_cost=Decimal("10.00"))

        assert finding.status == FindingStatus.UNRESOLVED
        assert "budget exceeded" in (finding.unresolved_reason or "").lower()
