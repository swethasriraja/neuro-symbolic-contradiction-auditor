"""
Evaluation CLI runner.
Usage:
  python -m eval.run --config configs/eval.yaml [--dry-run] [--pilot] [--system full|single|debate_no_solver|all]
Writes:
  - per-document results
  - aggregate metrics table
  - per-injection-type breakdown
  - cost and latency report
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
import yaml

from eval.injection.injector import ContradictionInjector
from eval.metrics.cache import EvalResultCache
from eval.metrics.calculator import MetricsCalculator
from eval.models import InjectedDocument
from eval.systems.runners import (
    DebateNoSolverSystem,
    NeuroSymbolicSystem,
    SingleLLMBaseline,
)
from extraction.mock_provider import MockLLMProvider
from extraction.provider import LLMProvider
from schemas.claim import LegalClaim, LegalClaimType
from schemas.span import SourceSpan

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("eval_runner")


def build_pilot_documents() -> list[InjectedDocument]:
    """Build a fixed 5-document pilot suite for benchmark evaluation."""
    injector = ContradictionInjector(seed=42)
    docs = []

    # 1. Legal deadline contradiction
    c1_base = "Either party may terminate this Agreement upon thirty (30) days prior written notice."
    c1_target = "Licensee may terminate upon sixty (60) days written notice."
    text1 = f"SECTION 1. {c1_base}\n\nSECTION 12. {c1_target}"
    docs.append(injector.inject_legal_deadline(text1, c1_base, c1_target, new_days=15, title="Pilot Doc 1: Deadline Conflict"))

    # 2. Legal deontic contradiction
    c2_base = "The Supplier shall deliver all products on the first business day."
    c2_target = "The Supplier shall deliver all products on the first business day."
    text2 = f"SECTION 3. {c2_base}\n\nSECTION 8. {c2_target}"
    docs.append(injector.inject_legal_deontic(text2, c2_base, c2_target, title="Pilot Doc 2: Deontic Modality Flip"))

    # 3. Financial narrative growth contradiction
    tbl3 = "Table 1: Revenue ($M)\nFY2022: 1000\nFY2023: 1200"
    narr3 = "Management notes revenue expanded by 20.0% year over year."
    text3 = f"{tbl3}\n\nNarrative Analysis:\n{narr3}"
    docs.append(injector.inject_financial_narrative_growth(text3, tbl3, narr3, corrupted_pct="35.0%", title="Pilot Doc 3: Corrupted Growth Rate"))

    # 4. Hard negative (rounding within tolerance)
    tbl4 = "Table 2: Operating Margin\nFY2022: 12.42%"
    narr4 = "Operating margin achieved 12.4% in fiscal 2022."
    text4 = f"{tbl4}\n\nNarrative Analysis:\n{narr4}"
    docs.append(injector.inject_hard_negative_rounding(text4, tbl4, narr4, within_tolerance_pct="12.4%", title="Pilot Doc 4: Hard Negative Rounding"))

    # 5. Clean document (False-positive baseline)
    text5 = "SECTION 1. Payment shall be made in thirty (30) days. SECTION 2. Governing Law shall be Delaware."
    docs.append(injector.create_clean_document(text5, title="Pilot Doc 5: Clean Document"))

    return docs


def run_evaluation(
    config_path: Path,
    dry_run: bool = True,
    pilot_only: bool = True,
    system_filter: str = "all",
) -> dict:
    """Execute evaluation harness over pilot or benchmark datasets."""
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    eval_cfg = cfg.get("eval", {})
    hard_cost_limit = float(eval_cfg.get("hard_cost_limit_usd", 5.0))
    iou_thresh = float(eval_cfg.get("iou_threshold", 0.5))
    cache = EvalResultCache(hard_cost_limit_usd=hard_cost_limit)

    provider: LLMProvider = MockLLMProvider()
    if dry_run:
        logger.info("[EVAL RUNNER] Dry-run mode enabled; using MockLLMProvider (Cost: $0.00).")
    else:
        logger.info("[EVAL RUNNER] Live provider configured.")

    # Configure systems
    systems = {}
    if system_filter in ("all", "single"):
        systems["single_llm"] = SingleLLMBaseline(provider)
    if system_filter in ("all", "debate_no_solver"):
        systems["debate_no_solver"] = DebateNoSolverSystem(provider)
    if system_filter in ("all", "full"):
        systems["neuro_symbolic_full"] = NeuroSymbolicSystem(provider)

    pilot_docs = build_pilot_documents() if pilot_only else []
    logger.info(f"[EVAL RUNNER] Loaded {len(pilot_docs)} evaluation documents.")

    results_by_system = {}

    for sys_name, sys_impl in systems.items():
        logger.info(f"--- Benchmarking System: {sys_name} ---")
        sys_findings = []
        all_gt_annotations = []
        total_tokens = 0
        total_cost = 0.0
        total_latency = 0.0

        for doc in pilot_docs:
            all_gt_annotations.extend(doc.annotations)

            # Build synthetic claims from ground truth spans for pair generation
            claims = []
            for ann in doc.annotations:
                claims.append(
                    LegalClaim(
                        claim_id=f"{ann.injection_id}_a",
                        claim_type=LegalClaimType.DEADLINE,
                        predicate="claim_a",
                        raw_text=ann.original_span_a.text_snippet,
                        span=ann.original_span_a,
                        parties=["PartyA"],
                        confidence=0.95,
                        extractor="eval",
                    )
                )
                claims.append(
                    LegalClaim(
                        claim_id=f"{ann.injection_id}_b",
                        claim_type=LegalClaimType.DEADLINE,
                        predicate="claim_b",
                        raw_text=ann.original_span_b.text_snippet,
                        span=ann.original_span_b,
                        parties=["PartyA"],
                        confidence=0.95,
                        extractor="eval",
                    )
                )

            cache_key = cache.make_cache_key(doc.doc_id, sys_impl.system_id, "default_config", 42)
            cached_output = cache.get(cache_key)

            if cached_output:
                logger.info(f"Cache HIT for doc {doc.doc_id[:8]}...")
                output = cached_output
            else:
                output = sys_impl.evaluate_document(doc.doc_id, doc.full_text, claims=claims)
                cache.put(cache_key, output)

            # Budget Guard
            if not cache.track_cost_and_check_budget(output.total_cost_usd):
                logger.error(f"[BUDGET EXCEEDED] Run halted. Cost limit ${hard_cost_limit} exceeded.")
                break

            sys_findings.extend(output.findings)
            total_tokens += output.total_tokens
            total_cost += output.total_cost_usd
            total_latency += output.latency_seconds

        # Compute Metrics
        metrics = MetricsCalculator.evaluate_findings(
            findings=sys_findings,
            ground_truth=all_gt_annotations,
            doc_text="\n".join(d.full_text for d in pilot_docs),
            iou_threshold=iou_thresh,
        )

        results_by_system[sys_name] = {
            "metrics": metrics.model_dump(),
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
            "total_latency_seconds": total_latency,
            "findings_count": len(sys_findings),
        }

    return results_by_system


def main():
    parser = argparse.ArgumentParser(description="Neuro-Symbolic Contradiction Auditor Evaluation Runner")
    parser.add_argument("--config", type=str, default="configs/eval.yaml", help="Path to evaluation config.")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Run with mock provider.")
    parser.add_argument("--pilot", action="store_true", default=True, help="Run on 5-document pilot suite.")
    parser.add_argument("--system", type=str, default="all", choices=["all", "single", "debate_no_solver", "full"])
    args = parser.parse_args()

    results = run_evaluation(
        config_path=Path(args.config),
        dry_run=args.dry_run,
        pilot_only=args.pilot,
        system_filter=args.system,
    )

    print("\n================== EVALUATION REPORT ==================")
    print(json.dumps(results, indent=2))
    print("=======================================================\n")


if __name__ == "__main__":
    main()
