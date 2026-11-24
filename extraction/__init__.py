"""
extraction package — LLM providers, prompts, and claim extractors.
"""

from extraction.gemini_provider import GeminiProvider
from extraction.defined_terms import DefinedTermExtractor
from extraction.financial import FinancialExtractor
from extraction.legal import LegalExtractor
from extraction.mock_provider import MockLLMProvider
from extraction.prompt_loader import load_prompt
from extraction.provider import LLMProvider, LLMResponse
from extraction.verifier import SpanVerificationError, SpanVerifier

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "GeminiProvider",
    "MockLLMProvider",
    "load_prompt",
    "SpanVerifier",
    "SpanVerificationError",
    "DefinedTermExtractor",
    "LegalExtractor",
    "FinancialExtractor",
]
