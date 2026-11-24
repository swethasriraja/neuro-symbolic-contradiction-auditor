"""
Judge Agent.
Synthesizes the debate record and verifier findings into a structured proposed verdict.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from agents.models import JudgeVerdict, VerifierEvaluation
from extraction.prompt_loader import load_prompt
from extraction.provider import LLMProvider, LLMResponse
from schemas.debate import AgentRole, DebateMessage
from schemas.pair import CandidatePair

logger = logging.getLogger(__name__)


class JudgeAgent:
    """Judicial agent that aggregates debate history and Verifier evidence."""

    def __init__(self, provider: LLMProvider, max_retries: int = 2):
        self.provider = provider
        self.max_retries = max_retries

    def adjudicate(
        self,
        pair: CandidatePair,
        debate_record_text: str,
        verifier_eval: VerifierEvaluation,
        thread_id: str,
        round_number: int,
    ) -> tuple[JudgeVerdict, DebateMessage]:
        """Produce Judge's proposed verdict."""
        prompt = load_prompt(
            "judge",
            version="v1",
            debate_record=debate_record_text,
            solver_outcome=verifier_eval.solver_result.outcome.value.upper(),
            spans_verified="YES" if verifier_eval.spans_verified else "NO",
            reconciliation_valid="YES" if verifier_eval.reconciliation_valid else "NO",
            reconciliation_reason=verifier_eval.reconciliation_reason or "none",
        )

        attempts = 0
        current_prompt = prompt
        # Safe default matching verifier outcome
        default_status = "contradiction" if verifier_eval.solver_result.outcome.value == "unsat" else "consistent"
        parsed_verdict = JudgeVerdict(
            proposed_status=default_status,
            confidence=0.95,
            severity="high" if default_status == "contradiction" else "info",
            title="Adjudicated Verdict",
            verdict_summary="Verdict adjudicated from debate record and solver verification.",
        )
        last_response: Optional[LLMResponse] = None

        while attempts <= self.max_retries:
            attempts += 1
            last_response = self.provider.generate(prompt=current_prompt, response_format="json")
            cleaned = last_response.text.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.strip("`").removeprefix("json").strip()
            try:
                data = json.loads(cleaned)
                parsed_verdict = JudgeVerdict.model_validate(data)
                break
            except Exception as e:
                logger.warning(f"[JudgeAgent] Attempt {attempts} validation error: {e}")
                current_prompt = f"{prompt}\n\nFix JSON format: {e}"

        assert last_response is not None
        message = DebateMessage(
            thread_id=thread_id,
            round_number=round_number,
            sender=AgentRole.JUDGE,
            claim_ids=[pair.claim_a.claim_id, pair.claim_b.claim_id],
            argument=parsed_verdict.verdict_summary,
            structured=parsed_verdict.model_dump(),
            model=last_response.model,
            prompt_tokens=last_response.prompt_tokens,
            completion_tokens=last_response.completion_tokens,
            cost_usd=last_response.cost_usd,
            latency_ms=last_response.latency_ms,
        )

        return parsed_verdict, message
