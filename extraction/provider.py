"""
LLM Provider abstraction and telemetry data classes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional


@dataclass(frozen=True)
class LLMResponse:
    """Standardized response from any LLM provider with mandatory telemetry."""
    text: str
    prompt: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: Decimal
    latency_ms: int
    seed: Optional[int] = None
    temperature: float = 0.0
    system_prompt: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class LLMProvider(ABC):
    """Abstract provider interface for swappable LLM access."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0,
        seed: Optional[int] = 42,
        response_format: str = "json",
    ) -> LLMResponse:
        """
        Generate text completion with full telemetry logging.

        Args:
            prompt: User prompt content.
            system_prompt: Optional system prompt.
            temperature: Sampling temperature (logged for determinism).
            seed: Random seed (logged for determinism).
            response_format: Expected output format ('json' | 'text').

        Returns:
            LLMResponse object with raw output and usage telemetry.
        """
        pass
