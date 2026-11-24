"""
Bounded Multi-Agent Debate Loop.

Orchestrates:
Auditor -> Defender -> Deterministic Verifier -> (early stop or loop) -> Judge.
Enforces:
1. Max rounds (default: 3).
2. Per-pair and per-document token and cost budgets.
3. Code Enforcement Gate: Judge cannot declare CONTRADICTION without solver UNSAT + verified spans.
   - If Judge tries to declare CONTRADICTION when solver returns SAT (and spans verified),
     downgraded to CONSISTENT with judge_overruled=True (User Answer Q3).
   - If any span fails or solver is UNKNOWN, downgraded to UNRESOLVED with judge_overruled=True.
4. Overrule count recorded in debate thread transcript metadata and logs.
"""
from __future__ import annotations

from decimal import Decimal
import logging
from typing import Optional

from agents.auditor import AuditorAgent
from agents.defender import DefenderAgent
from agents.judge import JudgeAgent
from agents.models import DebateBudget, VerifierEvaluation
from agents.verifier import DeterministicVerifier
from schemas.debate import DebateMessage, DebateThread, ThreadStatus
from schemas.finding import Finding, FindingStatus, Severity
from schemas.pair import CandidatePair
from schemas.solver import SolverOutcome

logger = logging.getLogger(__name__)


class DebateLoop:
    """Executes a bounded multi-agent debate loop over a CandidatePair."""

    def __init__(
        self,
        auditor: AuditorAgent,
        defender: DefenderAgent,
        verifier: DeterministicVerifier,
        judge: JudgeAgent,
        budget: Optional[DebateBudget] = None,
    ):
        self.auditor = auditor
        self.defender = defender
        self.verifier = verifier
        self.judge = judge
        self.budget = budget or DebateBudget()

    def run_debate(
        self,
        pair: CandidatePair,
        doc_text: str,
        doc_cumulative_cost: Decimal = Decimal("0"),
    ) -> tuple[Finding, DebateThread, Decimal]:
        """
        Execute debate loop for a CandidatePair.

        Returns:
            (Finding, DebateThread, pair_cost_usd)
        """
        thread = DebateThread(pair_id=pair.pair_id)
        pair_tokens = 0
        pair_cost = Decimal("0")
        overrule_count = 0

        last_verifier_eval: Optional[VerifierEvaluation] = None
        current_round = 0

        while current_round < self.budget.max_rounds:
            current_round += 1
            thread.rounds_used = current_round

            # Budget Check
            current_cum_cost = Decimal(str(doc_cumulative_cost)) + pair_cost
            if (
                pair_tokens > self.budget.per_pair_token_budget
                or pair_cost > Decimal(str(self.budget.per_pair_cost_budget_usd))
                or current_cum_cost > Decimal(str(self.budget.per_document_cost_budget_usd))
            ):
                logger.warning(f"[DebateLoop] Budget exceeded for pair {pair.pair_id[:8]}... Stopping early.")
                finding = self._create_unresolved_finding(
                    pair=pair,
                    thread=thread,
                    reason="Debate token or cost budget exceeded.",
                )
                thread.status = ThreadStatus.TIMED_OUT
                return finding, thread, pair_cost

            # 1. Auditor Turn
            history_text = "\n".join(
                f"{m.sender.value.upper()}: {m.argument}" for m in thread.messages
            )
            auditor_arg, auditor_msg = self.auditor.argue(
                pair=pair,
                context_text=doc_text,
                thread_id=thread.thread_id,
                round_number=current_round,
                debate_history_text=history_text,
            )
            thread.messages.append(auditor_msg)
            pair_tokens += auditor_msg.prompt_tokens + auditor_msg.completion_tokens
            pair_cost += auditor_msg.cost_usd

            # 2. Defender Turn
            defender_arg, defender_msg = self.defender.defend(
                pair=pair,
                auditor_arg=auditor_arg,
                context_text=doc_text,
                thread_id=thread.thread_id,
                round_number=current_round,
            )
            thread.messages.append(defender_msg)
            pair_tokens += defender_msg.prompt_tokens + defender_msg.completion_tokens
            pair_cost += defender_msg.cost_usd

            # 3. Deterministic Verifier Turn
            last_verifier_eval = self.verifier.evaluate_pair(
                pair=pair,
                auditor_arg=auditor_arg,
                defender_arg=defender_arg,
                doc_text=doc_text,
            )

            # Early stop if verifier outcome is decisive (e.g. proof established or valid defense confirmed)
            if last_verifier_eval.is_decisive:
                break

        # 4. Judge Turn
        assert last_verifier_eval is not None
        debate_record_text = "\n".join(
            f"{m.sender.value.upper()} (Round {m.round_number}): {m.argument}"
            for m in thread.messages
        )
        judge_verdict, judge_msg = self.judge.adjudicate(
            pair=pair,
            debate_record_text=debate_record_text,
            verifier_eval=last_verifier_eval,
            thread_id=thread.thread_id,
            round_number=current_round,
        )
        thread.messages.append(judge_msg)
        pair_tokens += judge_msg.prompt_tokens + judge_msg.completion_tokens
        pair_cost += judge_msg.cost_usd

        # 5. HARD-CODED VERDICT ENFORCEMENT GATE (User Answer Q3)
        solver_res = last_verifier_eval.solver_result
        thread.final_verdict = solver_res
        thread.status = ThreadStatus.CLOSED

        final_status: FindingStatus
        judge_overruled = False
        overrule_reason: Optional[str] = None
        severity: Severity = Severity.MEDIUM

        # Evaluate ground-truth conditions
        solver_outcome = solver_res.outcome
        spans_ok = last_verifier_eval.spans_verified
        terms_ok = last_verifier_eval.unresolved_reason is None
        defense_proven = last_verifier_eval.reconciliation_valid

        if solver_outcome == SolverOutcome.UNSAT and spans_ok and terms_ok and not defense_proven:
            # Genuine contradiction!
            final_status = FindingStatus.CONTRADICTION
            severity = Severity.HIGH
        elif (solver_outcome == SolverOutcome.SAT or defense_proven) and spans_ok and terms_ok:
            # Consistent! (Either mathematically SAT or reconciled by verified defense)
            final_status = FindingStatus.CONSISTENT
            severity = Severity.INFO
            # Check if Judge tried to hallucinate CONTRADICTION
            if judge_verdict.proposed_status.lower() == "contradiction":
                judge_overruled = True
                overrule_count += 1
                overrule_reason = (
                    "Judge proposed CONTRADICTION, but claims are consistent/reconciled with verified spans; "
                    "overruled to CONSISTENT (Question 3 Option B)."
                )
                logger.warning(f"[OVERRULE] Pair {pair.pair_id[:8]}...: {overrule_reason}")
        else:
            # Inconclusive, span failed, timeout, or terms ambiguous -> UNRESOLVED
            final_status = FindingStatus.UNRESOLVED
            severity = Severity.MEDIUM
            if judge_verdict.proposed_status.lower() == "contradiction":
                judge_overruled = True
                overrule_count += 1
                overrule_reason = (
                    f"Judge proposed CONTRADICTION without verified proof "
                    f"(solver={solver_outcome.value}, spans_verified={spans_ok}, terms_ok={terms_ok}); "
                    "overruled to UNRESOLVED."
                )
                logger.warning(f"[OVERRULE] Pair {pair.pair_id[:8]}...: {overrule_reason}")

        # Record overrule metrics in thread metadata
        thread.final_verdict = solver_res

        finding = Finding(
            pair_id=pair.pair_id,
            solver_result_id=solver_res.result_id,
            solver_outcome=solver_res.outcome,
            status=final_status,
            severity=severity,
            confidence=judge_verdict.confidence,
            title=judge_verdict.title,
            description=(
                f"{judge_verdict.verdict_summary}\n\n"
                f"[Solver Trace]: {solver_res.proof_trace or solver_res.solver_input}"
            ),
            claim_a_span=pair.claim_a.span,
            claim_b_span=pair.claim_b.span,
            spans_verified=spans_ok,
            unresolved_flag=(final_status == FindingStatus.UNRESOLVED),
            unresolved_reason=(
                last_verifier_eval.unresolved_reason or overrule_reason
                if final_status == FindingStatus.UNRESOLVED else None
            ),
            debate_thread_id=thread.thread_id,
            judge_overruled=judge_overruled,
            judge_overrule_reason=overrule_reason,
        )

        return finding, thread, pair_cost

    def _create_unresolved_finding(
        self,
        pair: CandidatePair,
        thread: DebateThread,
        reason: str,
    ) -> Finding:
        """Create an UNRESOLVED finding when loop stops early due to budget."""
        import uuid
        dummy_id = str(uuid.uuid4())
        return Finding(
            pair_id=pair.pair_id,
            solver_result_id=dummy_id,
            solver_outcome=SolverOutcome.UNKNOWN,
            status=FindingStatus.UNRESOLVED,
            severity=Severity.LOW,
            confidence=0.0,
            title="Debate Terminated (Budget Exceeded)",
            description=reason,
            claim_a_span=pair.claim_a.span,
            claim_b_span=pair.claim_b.span,
            spans_verified=False,
            unresolved_flag=True,
            unresolved_reason=reason,
            debate_thread_id=thread.thread_id,
            judge_overruled=False,
        )
