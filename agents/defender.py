"""
Defender Agent.
Argues candidate claims are reconcilable via scope, period, amendment, or definitions.
Uncited defenses carry zero weight.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from agents.models import AuditorArgument, DefenderArgument
from extraction.prompt_loader import load_prompt
from extraction.provider import LLMProvider, LLMResponse
from schemas.debate import AgentRole, DebateMessage
from schemas.pair import CandidatePair

logger = logging.getLogger(__name__)


class DefenderAgent:
    """Defender agent that seeks legitimate reconciliation grounds between claims."""

    def __init__(self, provider: LLMProvider, max_retries: int = 2):
        self.provider = provider
        self.max_retries = max_retries

    def defend(
        self,
        pair: CandidatePair,
        auditor_arg: AuditorArgument,
        context_text: str,
        thread_id: str,
        round_number: int,
    ) -> tuple[DefenderArgument, DebateMessage]:
        """Generate Defender argument for a candidate pair."""
        claim_a = pair.claim_a
        claim_b = pair.claim_b

        prompt = load_prompt(
            "defender",
            version="v1",
            claim_a_id=claim_a.claim_id,
            claim_a_text=claim_a.raw_text,
            claim_a_predicate=claim_a.predicate,
            claim_b_id=claim_b.claim_id,
            claim_b_text=claim_b.raw_text,
            claim_b_predicate=claim_b.predicate,
            auditor_assertion=auditor_arg.assertion,
            context_text=context_text[:3000],
        )

        attempts = 0
        current_prompt = prompt
        parsed_arg = DefenderArgument(
            reconciliation_type="none",
            explanation="No reconciliation found.",
            cited_claim_ids=[],
            reconciliation_basis="none",
            supporting_snippet="",
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
                parsed_arg = DefenderArgument.model_validate(data)
                break
            except Exception as e:
                logger.warning(f"[DefenderAgent] Attempt {attempts} validation error: {e}")
                current_prompt = f"{prompt}\n\nFix JSON format: {e}"

        assert last_response is not None
        message = DebateMessage(
            thread_id=thread_id,
            round_number=round_number,
            sender=AgentRole.DEFENDER,
            claim_ids=parsed_arg.cited_claim_ids or [claim_a.claim_id, claim_b.claim_id],
            argument=parsed_arg.explanation,
            structured=parsed_arg.model_dump(),
            model=last_response.model,
            prompt_tokens=last_response.prompt_tokens,
            completion_tokens=last_response.completion_tokens,
            cost_usd=last_response.cost_usd,
            latency_ms=last_response.latency_ms,
        )

        return parsed_arg, message
