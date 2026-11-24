"""
Mock LLM Provider for offline deterministic unit testing.
Enforces zero external network calls during test runs.
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Callable, Optional

from extraction.provider import LLMProvider, LLMResponse


class MockLLMProvider(LLMProvider):
    """
    Deterministic mock provider with scriptable responses and call logging.
    """

    def __init__(
        self,
        default_response: str = "[]",
        responder: Optional[Callable[[str], str]] = None,
        model_name: str = "mock-provider-v1",
    ):
        self.default_response = default_response
        self.responder = responder
        self.model_name = model_name
        self.call_history: list[dict] = []
        self._canned_queue: list[str] = []

    def queue_response(self, response_text: str) -> None:
        """Enqueue a specific response for the next generate() call."""
        self._canned_queue.append(response_text)

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        seed: Optional[int] = 42,
        response_format: str = "json",
    ) -> LLMResponse:
        if self._canned_queue:
            text = self._canned_queue.pop(0)
        elif self.responder:
            text = self.responder(prompt)
        else:
            text = self.default_response

        prompt_tokens = len(prompt.split())
        completion_tokens = len(text.split())
        cost_usd = Decimal("0.000000")
        latency_ms = 1

        record = {
            "prompt": prompt,
            "system_prompt": system_prompt,
            "text": text,
            "model": self.model_name,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cost_usd": cost_usd,
            "latency_ms": latency_ms,
            "seed": seed,
            "temperature": temperature,
        }
        self.call_history.append(record)

        return LLMResponse(
            text=text,
            prompt=prompt,
            model=self.model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            seed=seed,
            temperature=temperature,
            system_prompt=system_prompt,
        )
