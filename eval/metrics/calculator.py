"""
Evaluation metrics: Precision, Recall, F1, Evidence-Validity Rate, False-Positive Rate,
dual UNRESOLVED handling, and bootstrap confidence intervals.
"""
from __future__ import annotations

import math
from typing import Sequence
import numpy as np
from pydantic import BaseModel, ConfigDict

from eval.models import GroundTruthAnnotation, InjectionCategory
from schemas.finding import Finding, FindingStatus
from schemas.span import SourceSpan


class MetricResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    fn: int
    unresolved_count: int
    unresolved_rate: float
    evidence_validity_rate: float
    false_positive_rate_clean: float
    false_positive_rate_hard_negatives: float


class MetricsCalculator:
    """Calculates contradiction auditing evaluation metrics with span IoU matching."""

    @staticmethod
    def calculate_span_iou(span1: SourceSpan, span2: SourceSpan) -> float:
        """Compute 1D character interval Intersection over Union (IoU)."""
        inter_start = max(span1.char_start, span2.char_start)
        inter_end = min(span1.char_end, span2.char_end)
        inter_len = max(0, inter_end - inter_start)

        union_len = (span1.char_end - span1.char_start) + (span2.char_end - span2.char_start) - inter_len
        if union_len <= 0:
            return 0.0
        return float(inter_len / union_len)

    @classmethod
    def matches_ground_truth(
        cls,
        finding: Finding,
        annotation: GroundTruthAnnotation,
        iou_threshold: float = 0.5,
    ) -> bool:
        """Match finding against ground truth by checking pairwise span overlap."""
        if finding.status != FindingStatus.CONTRADICTION:
            return False
        if annotation.expected_verdict != FindingStatus.CONTRADICTION:
            return False

        # Match (span_a ~ gt_a and span_b ~ gt_b) OR (span_a ~ gt_b and span_b ~ gt_a)
        iou_a1 = cls.calculate_span_iou(finding.claim_a_span, annotation.original_span_a)
        iou_b2 = cls.calculate_span_iou(finding.claim_b_span, annotation.original_span_b)

        iou_a2 = cls.calculate_span_iou(finding.claim_a_span, annotation.original_span_b)
        iou_b1 = cls.calculate_span_iou(finding.claim_b_span, annotation.original_span_a)

        return (iou_a1 >= iou_threshold and iou_b2 >= iou_threshold) or (
            iou_a2 >= iou_threshold and iou_b1 >= iou_threshold
        )

    @classmethod
    def evaluate_findings(
        cls,
        findings: Sequence[Finding],
        ground_truth: Sequence[GroundTruthAnnotation],
        doc_text: str,
        iou_threshold: float = 0.5,
        exclude_unresolved: bool = False,
    ) -> MetricResult:
        """
        Evaluate predicted findings against ground truth annotations.
        Supports dual treatment of UNRESOLVED (counted as miss vs excluded).
        """
        # Partition ground truth
        contradiction_gts = [gt for gt in ground_truth if gt.expected_verdict == FindingStatus.CONTRADICTION]
        clean_gts = [gt for gt in ground_truth if gt.category == InjectionCategory.CLEAN]
        hn_gts = [gt for gt in ground_truth if gt.category == InjectionCategory.HARD_NEGATIVE]

        # 1. Evidence-Validity Rate (EVR)
        valid_spans = 0
        total_spans = 0
        for f in findings:
            for s in (f.claim_a_span, f.claim_b_span):
                total_spans += 1
                if 0 <= s.char_start < s.char_end <= len(doc_text):
                    if doc_text[s.char_start:s.char_end] == s.text_snippet:
                        valid_spans += 1
        evr = float(valid_spans / total_spans) if total_spans > 0 else 1.0

        # 2. Contradiction Confusion Matrix
        tp = 0
        fp = 0
        unresolved_count = 0
        matched_gt_ids = set()

        for f in findings:
            if f.status == FindingStatus.UNRESOLVED:
                unresolved_count += 1
                if not exclude_unresolved:
                    pass  # Counted as non-detection
                continue

            if f.status == FindingStatus.CONTRADICTION:
                matched = False
                for gt in contradiction_gts:
                    if gt.injection_id not in matched_gt_ids and cls.matches_ground_truth(f, gt, iou_threshold):
                        matched = True
                        matched_gt_ids.add(gt.injection_id)
                        tp += 1
                        break
                if not matched:
                    fp += 1

        total_gt = len(contradiction_gts)
        fn = total_gt - tp

        precision = float(tp / (tp + fp)) if (tp + fp) > 0 else 0.0
        recall = float(tp / (tp + fn)) if (tp + fn) > 0 else 0.0
        f1 = float(2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        # 3. False Positive Rates on Clean & Hard Negatives
        fp_clean = sum(
            1 for f in findings if f.status == FindingStatus.CONTRADICTION and any(gt.category == InjectionCategory.CLEAN for gt in ground_truth)
        )
        fpr_clean = float(fp_clean / len(clean_gts)) if clean_gts else 0.0

        fp_hn = sum(
            1 for f in findings if f.status == FindingStatus.CONTRADICTION and any(gt.category == InjectionCategory.HARD_NEGATIVE for gt in ground_truth)
        )
        fpr_hn = float(fp_hn / len(hn_gts)) if hn_gts else 0.0

        unresolved_rate = float(unresolved_count / len(findings)) if findings else 0.0

        return MetricResult(
            precision=precision,
            recall=recall,
            f1=f1,
            tp=tp,
            fp=fp,
            fn=fn,
            unresolved_count=unresolved_count,
            unresolved_rate=unresolved_rate,
            evidence_validity_rate=evr,
            false_positive_rate_clean=fpr_clean,
            false_positive_rate_hard_negatives=fpr_hn,
        )

    @staticmethod
    def bootstrap_confidence_intervals(
        values: list[float],
        n_bootstraps: int = 1000,
        ci: float = 0.95,
        seed: int = 42,
    ) -> tuple[float, float, float]:
        """Compute (mean, lower_ci, upper_ci) via bootstrap sampling."""
        if not values:
            return 0.0, 0.0, 0.0
        rng = np.random.default_rng(seed)
        boot_means = []
        n = len(values)
        for _ in range(n_bootstraps):
            sample = rng.choice(values, size=n, replace=True)
            boot_means.append(float(np.mean(sample)))

        alpha = (1.0 - ci) / 2.0
        lower = float(np.percentile(boot_means, alpha * 100))
        upper = float(np.percentile(boot_means, (1.0 - alpha) * 100))
        return float(np.mean(values)), lower, upper
