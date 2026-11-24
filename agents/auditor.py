"""
Auditor Agent.
Proposes contradiction theses for candidate pairs, citing exact claim IDs and verbatim spans.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from agents.models import AuditorArgument
from extraction.prompt_loader import load_prompt
from extraction.provider import LLMProvider, LLMResponse
from schemas.debate import AgentRole, DebateMessage
from schemas.pair import CandidatePair

logger = logging.getLogger(__name__)


class AuditorAgent:
    """Auditor agent that asserts potential contradictions between candidate claims."""

    def __init__(self, provider: LLMProvider, max_retries: int = 2):
        self.provider = provider
        self.max_retries = max_retries

    def argue(
        self,
        pair: CandidatePair,
        context_text: str,
        thread_id: str,
        round_number: int,
        debate_history_text: str = "",
    ) -> tuple[AuditorArgument, DebateMessage]:
        """Generate Auditor argument for a candidate pair."""
        claim_a = pair.claim_a
        claim_b = pair.claim_b

        prompt = load_prompt(
            "auditor",
            version="v1",
            claim_a_id=claim_a.claim_id,
            claim_a_type=getattr(claim_a, "claim_type", getattr(claim_a, "metric", "claim")),
            claim_a_text=claim_a.raw_text,
            claim_a_predicate=claim_a.predicate,
            claim_a_start=claim_a.span.char_start,
            claim_a_end=claim_a.span.char_end,
            claim_b_id=claim_b.claim_id,
            claim_b_type=getattr(claim_b, "claim_type", getattr(claim_b, "metric", "claim")),
            claim_b_text=claim_b.raw_text,
            claim_b_predicate=claim_b.predicate,
            claim_b_start=claim_b.span.char_start,
            claim_b_end=claim_b.span.char_end,
            context_text=context_text[:3000],
            debate_history=debate_history_text,
        )

        attempts = 0
        current_prompt = prompt
        parsed_arg = AuditorArgument(
            claim_ids=[claim_a.claim_id, claim_b.claim_id],
            contradiction_type="general",
            assertion=f"Clause {claim_a.claim_id[:8]} contradicts Clause {claim_b.claim_id[:8]}.",
            reasoning="Mutual logical exclusion.",
            cited_snippets=[claim_a.span.text_snippet, claim_b.span.text_snippet],
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
                parsed_arg = AuditorArgument.model_validate(data)
                break
            except Exception as e:
                logger.warning(f"[AuditorAgent] Attempt {attempts} validation error: {e}")
                current_prompt = f"{prompt}\n\nFix JSON format: {e}"

        assert last_response is not None
        message = DebateMessage(
            thread_id=thread_id,
            round_number=round_number,
            sender=AgentRole.AUDITOR,
            claim_ids=parsed_arg.claim_ids,
            argument=parsed_arg.reasoning,
            structured=parsed_arg.model_dump(),
            model=last_response.model,
            prompt_tokens=last_response.prompt_tokens,
            completion_tokens=last_response.completion_tokens,
            cost_usd=last_response.cost_usd,
            latency_ms=last_response.latency_ms,
        )

        return parsed_arg, message
