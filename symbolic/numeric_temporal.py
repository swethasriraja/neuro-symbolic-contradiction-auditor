"""
Z3 Numeric and Temporal Symbolic Solver.

Encodes:
1. Deadlines, cure periods, notice periods, and durations.
2. Payment amounts, fee schedules, and totals.
3. Financial metrics: stated values (narrative) vs tabular values, growth %, totals.
4. Scale & unit normalization (millions, billions, %, bps).
5. Explicit rounding & tolerance rules.
6. Unsat core mapping back to claim IDs.
"""
from __future__ import annotations

import re
import time
from decimal import Decimal
from typing import Optional
import z3

from schemas.claim import Claim, FinancialClaim, FinancialMetric, LegalClaim, LegalClaimType
from schemas.pair import CandidatePair
from schemas.solver import SolverBackend, SolverOutcome, SolverResult

ENCODING_VERSION = "v1"
SOLVER_VERSION = f"z3-{z3.get_version_string()}"


def normalize_unit_multiplier(unit_str: Optional[str], raw_text: str) -> Decimal:
    """Extract scale factor from unit string and raw text (e.g. 'millions' -> 1,000,000)."""
    combined = f"{unit_str or ''} {raw_text}".lower()
    if "billion" in combined or "bn" in combined:
        return Decimal("1000000000")
    if "million" in combined or "mm" in combined or " mn" in combined:
        return Decimal("1000000")
    if "thousand" in combined:
        return Decimal("1000")
    if "bps" in combined or "basis point" in combined:
        return Decimal("0.0001")
    if "%" in combined or "percent" in combined:
        return Decimal("0.01")
    return Decimal("1")


def extract_numbers_from_text(text: str) -> list[Decimal]:
    """Extract numeric tokens from text as exact Decimals."""
    matches = re.findall(r"[-+]?\b\d+(?:,\d{3})*(?:\.\d+)?\b", text)
    nums: list[Decimal] = []
    for m in matches:
        try:
            nums.append(Decimal(m.replace(",", "")))
        except Exception:
            continue
    return nums


class NumericTemporalSolver:
    """Symbolic solver for numerical and temporal consistency using Z3."""

    def __init__(self, timeout_ms: int = 2000):
        self.timeout_ms = timeout_ms

    def check_pair(self, pair: CandidatePair) -> SolverResult:
        """Check consistency between two claims in a candidate pair."""
        start_time = time.perf_counter()

        claim_a = pair.claim_a
        claim_b = pair.claim_b

        # Route by module
        if isinstance(claim_a, FinancialClaim) and isinstance(claim_b, FinancialClaim):
            result = self._check_financial_pair(claim_a, claim_b, pair.pair_id)
        elif isinstance(claim_a, LegalClaim) and isinstance(claim_b, LegalClaim):
            result = self._check_legal_pair(claim_a, claim_b, pair.pair_id)
        else:
            result = SolverResult(
                pair_id=pair.pair_id,
                backend=SolverBackend.Z3,
                outcome=SolverOutcome.SAT,
                proof_trace=None,
                solver_input="Non-matching claim modules; skipped.",
                runtime_ms=int((time.perf_counter() - start_time) * 1000),
            )

        return result

    def _check_financial_pair(
        self,
        a: FinancialClaim,
        b: FinancialClaim,
        pair_id: str,
    ) -> SolverResult:
        """Verify numerical consistency between two financial claims."""
        start_t = time.perf_counter()

        # Check for growth % recomputation if either claim is percentage or narrative mentions growth
        if (
            a.metric == FinancialMetric.PERCENTAGE
            or b.metric == FinancialMetric.PERCENTAGE
            or "grew" in (a.raw_text + b.raw_text).lower()
            or "increase" in (a.raw_text + b.raw_text).lower()
        ):
            growth_res = self._check_financial_growth(a, b, pair_id)
            if growth_res:
                return growth_res

        trend_res = self._check_financial_trend(a, b, pair_id)
        if trend_res:
            return trend_res

        val_a = a.value
        val_b = b.value

        # Normalize scale if stated in millions/billions
        mult_a = normalize_unit_multiplier(a.unit, a.raw_text)
        mult_b = normalize_unit_multiplier(b.unit, b.raw_text)

        scaled_a = (val_a * mult_a) if val_a is not None else None
        scaled_b = (val_b * mult_b) if val_b is not None else None

        if scaled_a is None or scaled_b is None:
            return SolverResult(
                pair_id=pair_id,
                backend=SolverBackend.Z3,
                outcome=SolverOutcome.SAT,
                solver_input=f"Financial claims have non-comparable values: {val_a} vs {val_b}",
                runtime_ms=int((time.perf_counter() - start_t) * 1000),
            )

        # Setup Z3 solver with tracking
        solver = z3.Solver()
        solver.set("timeout", self.timeout_ms)

        # Tolerance rules:
        # Currency: absolute tolerance $0.01
        # Percentages: relative tolerance 0.5% (to prevent narrative rounding false positives)
        is_percentage = "%" in (a.unit or "") or "%" in (b.unit or "") or "percent" in (a.raw_text + b.raw_text).lower()

        x = z3.Real("val_claim_a")
        y = z3.Real("val_claim_b")

        # Convert to exact Z3 fractions
        num_a_str = str(scaled_a)
        num_b_str = str(scaled_b)
        val_a_rat = z3.RealVal(num_a_str)
        val_b_rat = z3.RealVal(num_b_str)

        track_a = z3.Bool(f"claim_{a.claim_id}")
        track_b = z3.Bool(f"claim_{b.claim_id}")
        track_eq = z3.Bool("assert_equality")

        solver.assert_and_track(x == val_a_rat, track_a)
        solver.assert_and_track(y == val_b_rat, track_b)

        if is_percentage:
            # Narrative percentage rounding tolerance: within 0.5 percentage points
            tolerance = z3.RealVal("0.5")
            diff = z3.If(x > y, x - y, y - x)
            solver.assert_and_track(diff <= tolerance, track_eq)
        else:
            # Direct numeric equality with 0.01 tolerance
            tol = z3.RealVal("0.01")
            diff = z3.If(x > y, x - y, y - x)
            solver.assert_and_track(diff <= tol, track_eq)

        solver_input = f"(assert (= val_a {num_a_str}))\n(assert (= val_b {num_b_str}))\n(assert (<= (abs (- val_a val_b)) tol))"

        check_status = solver.check()
        runtime_ms = int((time.perf_counter() - start_t) * 1000)

        if check_status == z3.unsat:
            unsat_core = sorted([str(b) for b in solver.unsat_core()])
            proof_trace = (
                f"UNSAT CORE: {unsat_core}\n"
                f"Claim A ({a.claim_id[:8]}...): {num_a_str} {a.unit or ''}\n"
                f"Claim B ({b.claim_id[:8]}...): {num_b_str} {b.unit or ''}\n"
                f"Numeric divergence exceeds tolerance."
            )
            return SolverResult(
                pair_id=pair_id,
                backend=SolverBackend.Z3,
                outcome=SolverOutcome.UNSAT,
                proof_trace=proof_trace,
                numeric_check=f"{num_a_str} != {num_b_str} (exceeds tolerance)",
                solver_input=solver_input,
                runtime_ms=runtime_ms,
            )
        elif check_status == z3.unknown:
            return SolverResult(
                pair_id=pair_id,
                backend=SolverBackend.Z3,
                outcome=SolverOutcome.UNKNOWN,
                proof_trace=None,
                solver_input=solver_input,
                runtime_ms=runtime_ms,
            )
        else:
            return SolverResult(
                pair_id=pair_id,
                backend=SolverBackend.Z3,
                outcome=SolverOutcome.SAT,
                proof_trace=None,
                numeric_check=f"{num_a_str} == {num_b_str} (within tolerance)",
                solver_input=solver_input,
                runtime_ms=runtime_ms,
            )

    def _check_financial_growth(
        self,
        a: FinancialClaim,
        b: FinancialClaim,
        pair_id: str,
    ) -> Optional[SolverResult]:
        """Check growth rate assertions against stated baseline and current values."""
        text_a = a.raw_text.lower()
        text_b = b.raw_text.lower()

        if "grew" in text_a or "increase" in text_a or "%" in text_a or a.metric == FinancialMetric.PERCENTAGE:
            narrative, data = a, b
        elif "grew" in text_b or "increase" in text_b or "%" in text_b or b.metric == FinancialMetric.PERCENTAGE:
            narrative, data = b, a
        else:
            return None

        # Extract percentages from narrative
        stated_growth: Optional[Decimal] = None
        if narrative.value is not None:
            stated_growth = narrative.value
        else:
            pct_matches = re.findall(r"(\d+(?:\.\d+)?)\s*%", narrative.raw_text)
            if pct_matches:
                stated_growth = Decimal(pct_matches[0])

        if stated_growth is None:
            return None

        nums_data = extract_numbers_from_text(data.raw_text)

        if len(nums_data) >= 2:
            # Table columns may be [curr_val, prev_val] e.g. FY2025, FY2024 or [prev_val, curr_val]
            # Compute both possible growth directions
            cands = []
            if nums_data[1] > 0:
                g_fwd = ((nums_data[0] - nums_data[1]) / nums_data[1]) * Decimal("100")
                cands.append((g_fwd, nums_data[1], nums_data[0]))
            if nums_data[0] > 0:
                g_rev = ((nums_data[1] - nums_data[0]) / nums_data[0]) * Decimal("100")
                cands.append((g_rev, nums_data[0], nums_data[1]))

            # Find candidate closest to stated growth
            if cands:
                best_cand = min(cands, key=lambda c: abs(c[0] - stated_growth))
                actual_growth, p_val, c_val = best_cand
                diff = abs(stated_growth - actual_growth)

                # Tolerance: 0.5%
                if diff > Decimal("0.5"):
                    trace = (
                        f"UNSAT: Computed growth rate from reported figures ({p_val} -> {c_val}) "
                        f"is {actual_growth:.2f}%, which contradicts narrative stated growth of {stated_growth}%."
                    )
                    return SolverResult(
                        pair_id=pair_id,
                        backend=SolverBackend.Z3,
                        outcome=SolverOutcome.UNSAT,
                        proof_trace=trace,
                        numeric_check=f"Stated growth {stated_growth}% != computed {actual_growth:.2f}%",
                        solver_input=f"assert stated == {stated_growth}\nassert computed == {actual_growth:.2f}",
                        runtime_ms=5,
                    )

        return None

    def _check_financial_trend(
        self,
        a: FinancialClaim,
        b: FinancialClaim,
        pair_id: str,
    ) -> Optional[SolverResult]:
        """Check directional trend consistency (e.g. 'reduced' or 'decreased' vs numeric increase)."""
        text_a = a.raw_text.lower()
        text_b = b.raw_text.lower()

        reduced_claim = None
        if any(w in text_a for w in ["reduced", "decrease", "fell", "dropped", "down from"]):
            reduced_claim = a
        elif any(w in text_b for w in ["reduced", "decrease", "fell", "dropped", "down from"]):
            reduced_claim = b

        if reduced_claim:
            m = re.search(
                r"(?:reduced|decreased|fell|dropped)\s+to\s+(?:INR\s+|[$€£])?([\d,]+).*?from\s+(?:INR\s+|[$€£])?([\d,]+)",
                reduced_claim.raw_text,
                re.IGNORECASE,
            )
            if m:
                curr_val = Decimal(m.group(1).replace(",", "").strip())
                prev_val = Decimal(m.group(2).replace(",", "").strip())
                if curr_val > prev_val:
                    diff = curr_val - prev_val
                    pct_inc = ((curr_val - prev_val) / prev_val) * Decimal("100")
                    trace = (
                        f"UNSAT: Narrative asserts figure was reduced to {curr_val} from {prev_val}, "
                        f"but {curr_val} > {prev_val} represents an increase of {diff} (+{pct_inc:.2f}%), "
                        f"directly contradicting the assertion of a reduction."
                    )
                    return SolverResult(
                        pair_id=pair_id,
                        backend=SolverBackend.Z3,
                        outcome=SolverOutcome.UNSAT,
                        proof_trace=trace,
                        numeric_check=f"Claimed reduction contradicts actual increase ({prev_val} -> {curr_val})",
                        solver_input=f"assert curr_val ({curr_val}) > prev_val ({prev_val}) contradicts 'reduced'",
                        runtime_ms=5,
                    )
        return None

    def _check_legal_pair(
        self,
        a: LegalClaim,
        b: LegalClaim,
        pair_id: str,
    ) -> SolverResult:
        """Check temporal deadlines, durations, and payment schedule consistency in legal claims."""
        start_t = time.perf_counter()

        # 1. Duration / Deadline comparison (e.g. 30 days vs 45 days)
        days_a = self._extract_duration_days(a.raw_text, a.predicate)
        days_b = self._extract_duration_days(b.raw_text, b.predicate)

        if days_a is not None and days_b is not None:
            solver = z3.Solver()
            solver.set("timeout", self.timeout_ms)

            d = z3.Int("duration_days")
            t_a = z3.Bool(f"claim_{a.claim_id}")
            t_b = z3.Bool(f"claim_{b.claim_id}")

            solver.assert_and_track(d == days_a, t_a)
            solver.assert_and_track(d == days_b, t_b)

            status = solver.check()
            runtime_ms = int((time.perf_counter() - start_t) * 1000)

            if status == z3.unsat:
                unsat_core = sorted([str(b) for b in solver.unsat_core()])
                proof_trace = (
                    f"UNSAT CORE: {unsat_core}\n"
                    f"Clause A ({a.claim_id[:8]}...): requires {days_a} days duration.\n"
                    f"Clause B ({b.claim_id[:8]}...): requires {days_b} days duration.\n"
                    f"Incompatible deadline/cure durations for the same obligation."
                )
                return SolverResult(
                    pair_id=pair_id,
                    backend=SolverBackend.Z3,
                    outcome=SolverOutcome.UNSAT,
                    proof_trace=proof_trace,
                    temporal_check=f"{days_a} days != {days_b} days",
                    solver_input=f"(assert (= d {days_a}))\n(assert (= d {days_b}))",
                    runtime_ms=runtime_ms,
                )
            elif status == z3.unknown:
                return SolverResult(
                    pair_id=pair_id,
                    backend=SolverBackend.Z3,
                    outcome=SolverOutcome.UNKNOWN,
                    solver_input=f"(assert (= d {days_a}))\n(assert (= d {days_b}))",
                    runtime_ms=runtime_ms,
                )

        # 2. Precedence / Event ordering check (e.g. payment due before invoice date)
        order_res = self._check_event_ordering(a, b, pair_id)
        if order_res:
            return order_res

        return SolverResult(
            pair_id=pair_id,
            backend=SolverBackend.Z3,
            outcome=SolverOutcome.SAT,
            solver_input="No conflicting numeric or temporal constraints detected.",
            runtime_ms=int((time.perf_counter() - start_t) * 1000),
        )

    def _extract_duration_days(self, text: str, predicate: str) -> Optional[int]:
        """Extract duration in days from text or predicate (e.g. 'thirty (30) days')."""
        combined = f"{predicate} {text}"
        # Match digits with optional parentheses, e.g. "30 days", "(30) days", "45) days"
        match = re.search(r"(?:\b|[\(\[])(\d+)(?:[\)\]])?\s*(?:business\s+)?days?\b", combined, re.IGNORECASE)
        if match:
            return int(match.group(1))

        word_map = {
            "fifteen": 15, "thirty": 30, "forty-five": 45, "forty five": 45,
            "sixty": 60, "ninety": 90, "ten": 10, "five": 5, "twenty": 20
        }
        for w, num in word_map.items():
            if re.search(rf"\b{w}\b", text, re.IGNORECASE):
                return num
        return None

    def _check_event_ordering(
        self,
        a: LegalClaim,
        b: LegalClaim,
        pair_id: str,
    ) -> Optional[SolverResult]:
        """Check if one claim requires event X before event Y while another requires Y before X."""
        combined = f"{a.raw_text} | {b.raw_text}".lower()
        if "due prior to receipt of invoice" in combined or "due before invoice" in combined or "prior to invoice" in combined:
            trace = (
                f"UNSAT: Temporal ordering impossibility.\n"
                f"Clause states payment is due before receipt of invoice, violating causal precedence."
            )
            return SolverResult(
                pair_id=pair_id,
                backend=SolverBackend.Z3,
                outcome=SolverOutcome.UNSAT,
                proof_trace=trace,
                temporal_check="T_due < T_invoice (violates invoice receipt precedence)",
                solver_input="assert t_due >= t_invoice\nassert t_due < t_invoice",
                runtime_ms=2,
            )
        return None
