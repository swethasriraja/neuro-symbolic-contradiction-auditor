"""
Anthropic SDK provider implementation reading key from .env.
"""
from __future__ import annotations

import logging
import os
import time
from decimal import Decimal
from typing import Optional

from dotenv import load_dotenv

from extraction.provider import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

# Load .env file
load_dotenv()

# Pricing table per 1M tokens (USD)
# Claude 3.5 Sonnet default: $3.00 input, $15.00 output
MODEL_PRICING: dict[str, tuple[Decimal, Decimal]] = {
    "claude-3-5-sonnet-20241022": (Decimal("3.00"), Decimal("15.00")),
    "claude-3-5-sonnet-latest": (Decimal("3.00"), Decimal("15.00")),
    "claude-3-haiku-20240307": (Decimal("0.25"), Decimal("1.25")),
}


class AnthropicProvider(LLMProvider):
    """Concrete LLMProvider using the official Anthropic Python SDK."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "claude-3-5-sonnet-20241022",
    ):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is not set. Please add it to your .env file or pass it to AnthropicProvider."
            )
        self.model = model

        # Lazy import of anthropic
        import anthropic
        self.client = anthropic.Anthropic(api_key=self.api_key)

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        seed: Optional[int] = 42,
        response_format: str = "json",
    ) -> LLMResponse:
        start_time = time.perf_counter()

        messages = [{"role": "user", "content": prompt}]
        kwargs: dict = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 4096,
            "temperature": temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = self.client.messages.create(**kwargs)
        duration_ms = int((time.perf_counter() - start_time) * 1000)

        raw_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                raw_text += block.text

        prompt_tokens = response.usage.input_tokens
        completion_tokens = response.usage.output_tokens

        # Compute cost
        in_rate, out_rate = MODEL_PRICING.get(
            self.model, (Decimal("3.00"), Decimal("15.00"))
        )
        cost_usd = (
            (Decimal(prompt_tokens) / Decimal("1000000")) * in_rate
            + (Decimal(completion_tokens) / Decimal("1000000")) * out_rate
        ).quantize(Decimal("0.000001"))

        logger.info(
            f"[LLM Call] model={self.model} in_tokens={prompt_tokens} "
            f"out_tokens={completion_tokens} cost=${cost_usd} "
            f"latency={duration_ms}ms seed={seed} temp={temperature}"
        )

        return LLMResponse(
            text=raw_text,
            prompt=prompt,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            latency_ms=duration_ms,
            seed=seed,
            temperature=temperature,
            system_prompt=system_prompt,
        )
