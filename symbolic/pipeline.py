"""
No-Debate Contradiction Check Pipeline.

Implements the deterministic end-to-end audit:
claims -> term/scope resolution -> candidate pairs -> symbolic solvers -> span verification -> Finding.

NON-NEGOTIABLE PRINCIPLE:
A contradiction is CONFIRMED only if:
(a) Z3/Datalog proves UNSAT (or numeric/temporal check fails), AND
(b) every cited span is verified to exist in the source text (doc, page, section, char offsets).
Otherwise the verdict is CONSISTENT or UNRESOLVED. Never fabricate citations.
"""
from __future__ import annotations

import logging
from typing import Sequence

from extraction.verifier import SpanVerifier
from schemas.claim import Claim
from schemas.finding import Finding, FindingStatus, Severity
from schemas.pair import CandidatePair
from schemas.solver import SolverOutcome, SolverResult
from symbolic.candidate_pairs import CandidatePairGenerator
from symbolic.deontic import DeonticSolver
from symbolic.numeric_temporal import NumericTemporalSolver
from symbolic.terms import ScopeStatus, TermResolver

logger = logging.getLogger(__name__)


class NoDebatePipeline:
    """Deterministic, no-debate contradiction auditing pipeline."""

    def __init__(self, timeout_ms: int = 2000):
        self.numeric_solver = NumericTemporalSolver(timeout_ms=timeout_ms)
        self.deontic_solver = DeonticSolver(timeout_ms=timeout_ms)

    def audit_claims(
        self,
        claims: Sequence[Claim],
        doc_text: str,
    ) -> list[Finding]:
        """
        Execute deterministic contradiction auditing over a collection of claims.

        Args:
            claims: List of extracted LegalClaims or FinancialClaims from one document.
            doc_text: Source document text for strict span verification.

        Returns:
            List of auditable Findings (CONFIRMED, CONSISTENT, or UNRESOLVED).
        """
        findings: list[Finding] = []

        # 1. Deterministic pair generation
        pairs = CandidatePairGenerator.generate_pairs(claims)
        logger.info(f"[NoDebatePipeline] Formed {len(pairs)} candidate pairs.")

        for pair in pairs:
            # 2. Defined-Term & Scope Resolution Gate
            term_res = TermResolver.resolve_pair_scope(pair.claim_a, pair.claim_b)

            if not term_res.should_audit:
                if term_res.status in (ScopeStatus.CONFLICTING_DEFINITIONS, ScopeStatus.MISMATCHED_UNITS):
                    # Flag as UNRESOLVED for human review
                    findings.append(
                        self._create_unresolved_term_finding(pair, term_res.unresolved_reason or term_res.reason)
                    )
                continue

            # 3. Solver Dispatch
            # Try numeric/temporal solver first, then deontic
            solver_res = self.numeric_solver.check_pair(pair)
            if solver_res.outcome == SolverOutcome.SAT and pair.claim_a.module == "legal":
                # Check deontic conflicts
                deontic_res = self.deontic_solver.check_pair(pair)
                if deontic_res.outcome == SolverOutcome.UNSAT:
                    solver_res = deontic_res

            # 4. Strict Span Verification Gate
            valid_a, reason_a = SpanVerifier.verify_claim(doc_text, pair.claim_a)
            valid_b, reason_b = SpanVerifier.verify_claim(doc_text, pair.claim_b)
            spans_verified = valid_a and valid_b

            # 5. Build Finding with strict invariants
            finding = self._build_finding(
                pair=pair,
                solver_res=solver_res,
                spans_verified=spans_verified,
                span_failure_reason=reason_a or reason_b,
            )
            findings.append(finding)

        return findings

    def _build_finding(
        self,
        pair: CandidatePair,
        solver_res: SolverResult,
        spans_verified: bool,
        span_failure_reason: str | None,
    ) -> Finding:
        """Construct a Finding enforcing all invariant validation rules."""
        if solver_res.outcome == SolverOutcome.UNSAT:
            if spans_verified:
                # CONTRADICTION verdict!
                return Finding(
                    pair_id=pair.pair_id,
                    solver_result_id=solver_res.result_id,
                    solver_outcome=SolverOutcome.UNSAT,
                    status=FindingStatus.CONTRADICTION,
                    severity=Severity.HIGH,
                    confidence=0.98,
                    title="Confirmed Contradiction",
                    description=(
                        f"Symbolic solver confirmed contradiction via {solver_res.backend.value.upper()}.\n"
                        f"{solver_res.proof_trace or ''}"
                    ),
                    claim_a_span=pair.claim_a.span,
                    claim_b_span=pair.claim_b.span,
                    spans_verified=True,
                    unresolved_flag=False,
                )
            else:
                # Solver confirmed conflict, but citation span failed verification -> UNRESOLVED
                return Finding(
                    pair_id=pair.pair_id,
                    solver_result_id=solver_res.result_id,
                    solver_outcome=solver_res.outcome,
                    status=FindingStatus.UNRESOLVED,
                    severity=Severity.MEDIUM,
                    confidence=0.50,
                    title="Unresolved Contradiction (Span Verification Failed)",
                    description=(
                        f"Solver found logical contradiction, but one or both cited spans "
                        f"failed verification against the source document ({span_failure_reason})."
                    ),
                    claim_a_span=pair.claim_a.span,
                    claim_b_span=pair.claim_b.span,
                    spans_verified=False,
                    unresolved_flag=True,
                    unresolved_reason=f"Span verification failure: {span_failure_reason}",
                )

        elif solver_res.outcome == SolverOutcome.UNKNOWN:
            # Solver timeout or error -> UNRESOLVED
            return Finding(
                pair_id=pair.pair_id,
                solver_result_id=solver_res.result_id,
                solver_outcome=solver_res.outcome,
                status=FindingStatus.UNRESOLVED,
                severity=Severity.MEDIUM,
                confidence=0.0,
                title="Unresolved (Solver Timeout or Error)",
                description=f"Symbolic solver encountered {solver_res.outcome.value.upper()}.",
                claim_a_span=pair.claim_a.span,
                claim_b_span=pair.claim_b.span,
                spans_verified=spans_verified,
                unresolved_flag=True,
                unresolved_reason=f"Solver outcome: {solver_res.outcome.value}",
            )

        else:
            # Satisfiable -> CONSISTENT
            return Finding(
                pair_id=pair.pair_id,
                solver_result_id=solver_res.result_id,
                solver_outcome=SolverOutcome.SAT,
                status=FindingStatus.CONSISTENT,
                severity=Severity.INFO,
                confidence=0.99,
                title="Consistent Claims",
                description="Claims are mutually satisfiable and logically consistent.",
                claim_a_span=pair.claim_a.span,
                claim_b_span=pair.claim_b.span,
                spans_verified=spans_verified,
                unresolved_flag=False,
            )

    def _create_unresolved_term_finding(
        self,
        pair: CandidatePair,
        reason: str | None,
    ) -> Finding:
        """Create an UNRESOLVED finding when defined-term resolution detects ambiguity."""
        import uuid
        dummy_result_id = str(uuid.uuid4())
        return Finding(
            pair_id=pair.pair_id,
            solver_result_id=dummy_result_id,
            solver_outcome=SolverOutcome.SAT,
            status=FindingStatus.UNRESOLVED,
            severity=Severity.MEDIUM,
            confidence=0.5,
            title="Unresolved Defined Term / Scope Ambiguity",
            description=f"Flagged by pre-solver scope resolver: {reason}",
            claim_a_span=pair.claim_a.span,
            claim_b_span=pair.claim_b.span,
            spans_verified=False,
            unresolved_flag=True,
            unresolved_reason=reason or "Defined term scope ambiguity.",
        )
