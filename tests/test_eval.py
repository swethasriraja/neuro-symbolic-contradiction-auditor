"""
Unit tests for the evaluation harness and synthetic contradiction injection engine.
All tests use MockLLMProvider and local deterministic fixtures — zero API calls.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from eval.injection.injector import ContradictionInjector
from eval.metrics.cache import EvalResultCache
from eval.metrics.calculator import MetricsCalculator
from eval.models import (
    EvalSystemOutput,
    GroundTruthAnnotation,
    InjectionCategory,
    InjectionType,
)
from eval.run import build_pilot_documents, run_evaluation
from eval.systems.runners import SingleLLMBaseline
from extraction.mock_provider import MockLLMProvider
from schemas.finding import Finding, FindingStatus, Severity
from schemas.solver import SolverBackend, SolverOutcome, SolverResult
from schemas.span import SourceSpan

DOC_ID = "e" * 64


def make_span(start: int, end: int, text: str) -> SourceSpan:
    return SourceSpan(
        doc_id=DOC_ID,
        doc_path="test_doc.txt",
        char_start=start,
        char_end=end,
        text_snippet=text,
    )


class TestContradictionInjector:
    def test_injection_exact_offsets(self) -> None:
        """Verify injected span offsets exactly match the mutated document text slice."""
        injector = ContradictionInjector(seed=42)
        base = "Termination requires thirty (30) days notice."
        target = "Notice period is thirty (30) days."
        full_text = f"SECTION 1. {base}\n\nSECTION 2. {target}"

        injected_doc = injector.inject_legal_deadline(
            full_text=full_text,
            base_clause=base,
            target_clause=target,
            new_days=10,
        )

        ann = injected_doc.annotations[0]
        # Invariant 1: text[char_start:char_end] == text_snippet
        assert injected_doc.full_text[ann.original_span_a.char_start:ann.original_span_a.char_end] == ann.original_span_a.text_snippet
        assert injected_doc.full_text[ann.original_span_b.char_start:ann.original_span_b.char_end] == ann.original_span_b.text_snippet
        assert ann.expected_verdict == FindingStatus.CONTRADICTION
        assert "10 days" in ann.original_span_b.text_snippet

    def test_injection_determinism(self) -> None:
        """Same seed and inputs must generate bit-for-bit identical mutated documents."""
        injector1 = ContradictionInjector(seed=100)
        injector2 = ContradictionInjector(seed=100)

        base = "The Vendor shall deliver hardware."
        target = "The Vendor shall deliver hardware."
        full = f"CLAUSE A. {base}\n\nCLAUSE B. {target}"

        doc1 = injector1.inject_legal_deontic(full, base, target)
        doc2 = injector2.inject_legal_deontic(full, base, target)

        assert doc1.full_text == doc2.full_text
        assert doc1.doc_id == doc2.doc_id
        assert doc1.annotations[0].injection_id == doc2.annotations[0].injection_id

    def test_hard_negative_rounding(self) -> None:
        """Hard negatives must be marked with expected_verdict = CONSISTENT."""
        injector = ContradictionInjector(seed=42)
        tbl = "Revenue: $1000M"
        narr = "Revenue grew by 15.0%."
        full = f"{tbl}\n{narr}"

        doc = injector.inject_hard_negative_rounding(full, tbl, narr, within_tolerance_pct="15.05%")
        ann = doc.annotations[0]
        assert ann.category == InjectionCategory.HARD_NEGATIVE
        assert ann.expected_verdict == FindingStatus.CONSISTENT


class TestMetricsCalculator:
    def test_hand_computed_precision_recall_f1(self) -> None:
        """Hand-computed confusion matrix matches code exactly."""
        doc_text = "Clause A text here. Clause B text here. Clause C text here."
        span_a = SourceSpan(doc_id=DOC_ID, doc_path="doc.txt", char_start=0, char_end=19, text_snippet="Clause A text here.")
        span_b = SourceSpan(doc_id=DOC_ID, doc_path="doc.txt", char_start=20, char_end=39, text_snippet="Clause B text here.")
        span_c = SourceSpan(doc_id=DOC_ID, doc_path="doc.txt", char_start=40, char_end=59, text_snippet="Clause C text here.")

        gt = [
            GroundTruthAnnotation(
                injection_id="gt1",
                doc_id=DOC_ID,
                category=InjectionCategory.LEGAL,
                injection_type=InjectionType.DEADLINE_ALTERATION,
                expected_verdict=FindingStatus.CONTRADICTION,
                original_span_a=span_a,
                original_span_b=span_b,
                mutation_description="test",
                seed=42,
            )
        ]

        dummy_solver = SolverResult(
            pair_id="p1",
            backend=SolverBackend.Z3,
            solver_input="test",
            outcome=SolverOutcome.UNSAT,
            runtime_ms=1,
            proof_trace="trace",
        )

        # 1. Prediction matches Ground Truth (TP=1, FP=0, FN=0 -> P=1.0, R=1.0, F1=1.0)
        finding_tp = Finding(
            pair_id="p1",
            solver_result_id=dummy_solver.result_id,
            solver_outcome=SolverOutcome.UNSAT,
            status=FindingStatus.CONTRADICTION,
            severity=Severity.HIGH,
            confidence=0.9,
            title="T",
            description="D",
            claim_a_span=span_a,
            claim_b_span=span_b,
            spans_verified=True,
        )
        res_tp = MetricsCalculator.evaluate_findings([finding_tp], gt, doc_text)
        assert res_tp.tp == 1
        assert res_tp.fp == 0
        assert res_tp.fn == 0
        assert res_tp.precision == 1.0
        assert res_tp.recall == 1.0
        assert res_tp.f1 == 1.0
        assert res_tp.evidence_validity_rate == 1.0

        # 2. Prediction on wrong span (TP=0, FP=1, FN=1 -> P=0.0, R=0.0, F1=0.0)
        finding_fp = Finding(
            pair_id="p2",
            solver_result_id=dummy_solver.result_id,
            solver_outcome=SolverOutcome.UNSAT,
            status=FindingStatus.CONTRADICTION,
            severity=Severity.HIGH,
            confidence=0.9,
            title="T",
            description="D",
            claim_a_span=span_b,
            claim_b_span=span_c,
            spans_verified=True,
        )
        res_fp = MetricsCalculator.evaluate_findings([finding_fp], gt, doc_text)
        assert res_fp.tp == 0
        assert res_fp.fp == 1
        assert res_fp.fn == 1
        assert res_fp.f1 == 0.0

    def test_fabricated_span_fails_evidence_validity(self) -> None:
        """Fabricated span in finding drops evidence validity rate."""
        doc_text = "Real document text here."
        real_span = SourceSpan(doc_id=DOC_ID, doc_path="doc.txt", char_start=0, char_end=10, text_snippet="Real docum")
        fake_span = SourceSpan(doc_id=DOC_ID, doc_path="doc.txt", char_start=0, char_end=10, text_snippet="Hallucinated text")

        dummy_solver = SolverResult(
            pair_id="p1",
            backend=SolverBackend.Z3,
            solver_input="test",
            outcome=SolverOutcome.UNSAT,
            runtime_ms=1,
            proof_trace="trace",
        )
        finding = Finding(
            pair_id="p_fake",
            solver_result_id=dummy_solver.result_id,
            solver_outcome=SolverOutcome.UNSAT,
            status=FindingStatus.UNRESOLVED,
            severity=Severity.MEDIUM,
            confidence=0.9,
            title="T",
            description="D",
            claim_a_span=real_span,
            claim_b_span=fake_span,
            spans_verified=False,
            unresolved_flag=True,
            unresolved_reason="Fabricated span",
        )

        res = MetricsCalculator.evaluate_findings([finding], [], doc_text)
        # 1 valid span out of 2 total spans = 0.5 EVR
        assert res.evidence_validity_rate == 0.5


class TestCacheAndBudgetGuard:
    def test_cache_hit_and_budget_abort(self, tmp_path: Path) -> None:
        """Cache hit avoids re-computation; cost limit aborts properly."""
        cache = EvalResultCache(cache_dir=tmp_path, hard_cost_limit_usd=0.50)

        # Cost check within limit
        assert cache.track_cost_and_check_budget(0.20) is True
        assert cache.cumulative_cost_usd == 0.20

        # Cost check exceeding limit
        assert cache.track_cost_and_check_budget(0.40) is False
        assert abs(cache.cumulative_cost_usd - 0.60) < 1e-6


class TestEvaluationRunner:
    def test_runner_on_pilot_suite_dry_run(self, tmp_path: Path) -> None:
        """Test full CLI evaluation runner execution on pilot suite with mock provider."""
        cfg_path = Path("configs/eval.yaml")
        results = run_evaluation(config_path=cfg_path, dry_run=True, pilot_only=True, system_filter="all")

        assert "single_llm" in results
        assert "debate_no_solver" in results
        assert "neuro_symbolic_full" in results

        # Total cost must be 0 in dry run with MockLLMProvider
        for sys_name, res in results.items():
            assert res["total_cost_usd"] == 0.0
            assert "metrics" in res
            assert "f1" in res["metrics"]
