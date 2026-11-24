"""
Defined-Term Extractor — first-class preliminary extraction pass.

Extracts defined terms (e.g. "Business Day" vs "day") from contracts
and compiles a resolved glossary for scope handling downstream.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from extraction.prompt_loader import load_prompt
from extraction.provider import LLMProvider
from ingestion.models import ParsedDocument

logger = logging.getLogger(__name__)


class DefinedTermExtractor:
    """
    Extracts contract defined terms using regex heuristics combined with
    an optional LLM pass over definitions sections.
    """

    # Regex for standard legal definition patterns
    # e.g.: "Business Day" means ...
    #       "Effective Date" shall refer to ...
    #       "Confidential Information" has the meaning ...
    TERM_REGEX = re.compile(
        r'["“]([A-Z][A-Za-z0-9\s\-_/]+)["”]\s+(?:means|shall mean|refers to|shall refer to|has the meaning(?: given)?)\s+([^.;\n]{5,200})',
        re.IGNORECASE,
    )

    def __init__(self, provider: Optional[LLMProvider] = None, prompt_version: str = "v1"):
        self.provider = provider
        self.prompt_version = prompt_version

    def extract_from_text(self, text: str) -> dict[str, str]:
        """Extract defined terms using regex pattern matching."""
        terms: dict[str, str] = {}
        for match in self.TERM_REGEX.finditer(text):
            term = match.group(1).strip()
            definition = match.group(2).strip()
            if term and definition and term not in terms:
                terms[term] = definition
        return terms

    def extract_from_document(self, doc: ParsedDocument) -> dict[str, str]:
        """
        Extract definitions across the whole document.
        First scans sections titled 'Definitions' or 'Defined Terms', then falls back to whole text.
        """
        terms: dict[str, str] = {}

        # 1. Check for dedicated definitions sections
        definitions_text_parts: list[str] = []
        for sec in doc.sections:
            if any(k in sec.title.lower() for k in ["definition", "defined term", "interpretation"]):
                definitions_text_parts.append(doc.full_text[sec.char_start : sec.char_end])

        target_text = "\n\n".join(definitions_text_parts) if definitions_text_parts else doc.full_text

        # 2. Run regex extraction
        terms.update(self.extract_from_text(target_text))

        # 3. If LLM provider is available and terms found are low, run LLM pass on the definitions text
        if self.provider and len(terms) < 3 and len(target_text.strip()) > 50:
            try:
                llm_terms = self._extract_via_llm(target_text[:4000])
                for k, v in llm_terms.items():
                    if k not in terms:
                        terms[k] = v
            except Exception as e:
                logger.warning(f"LLM defined-term extraction pass failed: {e}")

        logger.info(f"Extracted {len(terms)} defined terms from {doc.doc_path}")
        return terms

    def _extract_via_llm(self, text_slice: str) -> dict[str, str]:
        """Execute LLM call to extract defined terms."""
        if not self.provider:
            return {}
        prompt = load_prompt("defined_terms", version=self.prompt_version, text=text_slice)
        response = self.provider.generate(prompt=prompt, response_format="json")
        cleaned = response.text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").removeprefix("json").strip()
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
        return {}
