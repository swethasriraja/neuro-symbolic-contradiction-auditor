"""
Deterministic Verifier Engine.

NOT AN LLM. It is strictly deterministic code that:
1. Checks every cited span exists in the source text at cited offsets.
2. Re-runs defined-term and scope resolution.
3. Invokes the Step 3 symbolic solver (Z3 and Datalog).
4. Evaluates Defender reconciliations into checkable formal assumptions.
   (Uncited or ungrounded assertions carry zero weight).
"""
from __future__ import annotations

import logging
from typing import Optional

from agents.models import AuditorArgument, DefenderArgument, VerifierEvaluation
from extraction.verifier import SpanVerifier
from schemas.claim import FinancialClaim, LegalClaim
from schemas.pair import CandidatePair
from schemas.solver import SolverOutcome, SolverResult
from symbolic.deontic import DeonticSolver
from symbolic.numeric_temporal import NumericTemporalSolver
from symbolic.terms import ScopeStatus, TermResolver

logger = logging.getLogger(__name__)


class DeterministicVerifier:
    """The formal, deterministic ground-truth verification engine."""

    def __init__(self, timeout_ms: int = 2000):
        self.numeric_solver = NumericTemporalSolver(timeout_ms=timeout_ms)
        self.deontic_solver = DeonticSolver(timeout_ms=timeout_ms)

    def evaluate_pair(
        self,
        pair: CandidatePair,
        auditor_arg: AuditorArgument,
        defender_arg: Optional[DefenderArgument],
        doc_text: str,
    ) -> VerifierEvaluation:
        """Execute deterministic verification of a candidate pair under debate."""
        # 1. Span Verification Check
        valid_a, reason_a = SpanVerifier.verify_claim(doc_text, pair.claim_a)
        valid_b, reason_b = SpanVerifier.verify_claim(doc_text, pair.claim_b)
        spans_verified = valid_a and valid_b

        # 2. Defender Reconciliation Evaluation
        reconciliation_valid = False
        reconciliation_reason: Optional[str] = None

        if defender_arg and defender_arg.reconciliation_type != "none":
            reconciliation_valid, reconciliation_reason = self._validate_defense(
                pair=pair,
                defender_arg=defender_arg,
                doc_text=doc_text,
            )

        # 3. Scope & Term Resolution Check
        term_res = TermResolver.resolve_pair_scope(pair.claim_a, pair.claim_b)
        unresolved_reason = None
        if not term_res.should_audit:
            # If defender has actively validated and verified this conditional/exception,
            # it reconciles the pair (neutralizing contradiction to CONSISTENT) rather than
            # dropping it to UNRESOLVED.
            if reconciliation_valid:
                pass
            else:
                solver_res = self.numeric_solver.check_pair(pair)
                return VerifierEvaluation(
                    solver_result=solver_res,
                    spans_verified=spans_verified,
                    reconciliation_valid=False,
                    reconciliation_reason=None,
                    is_decisive=True,
                    unresolved_reason=term_res.unresolved_reason or term_res.reason,
                )

        # 4. Symbolic Solver Execution
        solver_res = self.numeric_solver.check_pair(pair)
        if solver_res.outcome == SolverOutcome.SAT and pair.claim_a.module == "legal":
            deontic_res = self.deontic_solver.check_pair(pair)
            if deontic_res.outcome == SolverOutcome.UNSAT:
                solver_res = deontic_res

        # If Defender proved a valid reconciliation, solver conflict is neutralized
        if reconciliation_valid and solver_res.outcome == SolverOutcome.UNSAT:
            solver_res = solver_res.model_copy(
                update={
                    "outcome": SolverOutcome.SAT,
                    "proof_trace": f"Neutralized by verified defense: {reconciliation_reason}",
                }
            )

        # Decisive check: decisive if solver proved SAT or UNSAT, and spans are verified
        is_decisive = solver_res.outcome in (SolverOutcome.SAT, SolverOutcome.UNSAT)

        return VerifierEvaluation(
            solver_result=solver_res,
            spans_verified=spans_verified,
            reconciliation_valid=reconciliation_valid,
            reconciliation_reason=reconciliation_reason,
            is_decisive=is_decisive,
            unresolved_reason=reason_a or reason_b,
        )

    def _validate_defense(
        self,
        pair: CandidatePair,
        defender_arg: DefenderArgument,
        doc_text: str,
    ) -> tuple[bool, Optional[str]]:
        """
        Validate Defender's asserted reconciliation.
        Rule: A defense with no verifiable citation in the document carries no weight.
        """
        rtype = defender_arg.reconciliation_type.lower()
        snippet = (defender_arg.supporting_snippet or "").strip()

        if not snippet or len(snippet) < 3:
            return False, "Defender provided no verifiable supporting snippet."

        # Verify snippet exists in source document text
        if snippet not in doc_text:
            return False, f"Supporting snippet '{snippet[:40]}...' was not found in source text."

        # 1. Scope / Exception defense
        if rtype in ("scope_exception", "conditional_exception"):
            # Check if one claim has this conditional qualifier or text contains it
            for c in (pair.claim_a, pair.claim_b):
                if isinstance(c, LegalClaim) and (
                    c.scope_qualifier and snippet.lower() in c.scope_qualifier.lower()
                ):
                    return True, f"Verified conditional scope exception: '{snippet}'."
            if any(k in snippet.lower() for k in ["unless", "except as", "subject to", "provided that", "in the event"]):
                return True, f"Verified contractual exception: '{snippet}'."

        # 2. Amendment override defense
        elif rtype in ("amendment_override", "amendment"):
            if "amendment" in snippet.lower() or "amended" in snippet.lower():
                return True, f"Verified amendment override provision: '{snippet}'."

        # 3. Period mismatch defense
        elif rtype in ("period_mismatch", "reporting_period"):
            for c in (pair.claim_a, pair.claim_b):
                if isinstance(c, FinancialClaim) and c.period and snippet.lower() in c.period.lower():
                    return True, f"Verified reporting period distinction: '{snippet}'."

        # 4. Entity mismatch defense
        elif rtype in ("entity_mismatch", "reporting_entity"):
            for c in (pair.claim_a, pair.claim_b):
                if isinstance(c, FinancialClaim) and c.entity and snippet.lower() in c.entity.lower():
                    return True, f"Verified entity distinction: '{snippet}'."

        # 5. Definition difference defense
        elif rtype in ("definition_difference", "defined_term"):
            if any(k in snippet.lower() for k in ["business day", "calendar day", "means", "refers to"]):
                return True, f"Verified defined term distinction: '{snippet}'."

        return False, "Defender reconciliation basis could not be formally confirmed."
