"""
Legal Claim Extractor with retry loop and strict span verification.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from pydantic import ValidationError

from extraction.prompt_loader import load_prompt
from extraction.provider import LLMProvider, LLMResponse
from extraction.verifier import SpanVerifier
from schemas.chunk import Chunk
from schemas.claim import LegalClaim, LegalClaimType
from schemas.span import SourceSpan

logger = logging.getLogger(__name__)


class LegalExtractor:
    """
    Extracts LegalClaims from contract chunks using versioned prompts,
    enforcing Pydantic validation, retry loops, and strict span verification.
    """

    def __init__(
        self,
        provider: LLMProvider,
        prompt_version: str = "v1",
        max_retries: int = 2,
    ):
        self.provider = provider
        self.prompt_version = prompt_version
        self.max_retries = max_retries

    def extract_claims_from_chunk(
        self,
        chunk: Chunk,
        defined_terms: Optional[dict[str, str]] = None,
        doc_full_text: Optional[str] = None,
    ) -> list[LegalClaim]:
        """
        Extract all LegalClaims from a contract chunk.

        Args:
            chunk: Input Chunk.
            defined_terms: Resolved contract glossary dictionary.
            doc_full_text: Full document text (for global span verification).

        Returns:
            List of verified LegalClaims.
        """
        defined_terms = defined_terms or {}
        defined_terms_json = json.dumps(defined_terms, indent=2)

        prompt = load_prompt(
            "legal",
            version=self.prompt_version,
            chunk_text=chunk.text,
            defined_terms_json=defined_terms_json,
        )

        attempts = 0
        current_prompt = prompt
        extracted_claims: list[LegalClaim] = []

        while attempts <= self.max_retries:
            attempts += 1
            response: LLMResponse = self.provider.generate(
                prompt=current_prompt,
                response_format="json",
            )

            raw_text = response.text.strip()
            # Strip markdown code blocks if present
            if raw_text.startswith("```"):
                lines = raw_text.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                raw_text = "\n".join(lines).strip()

            try:
                raw_items = json.loads(raw_text)
                if not isinstance(raw_items, list):
                    raise ValueError(f"Expected JSON array of claims, got {type(raw_items).__name__}")

                parsed_chunk_claims = self._parse_and_verify_items(
                    raw_items=raw_items,
                    chunk=chunk,
                    defined_terms=defined_terms,
                    doc_full_text=doc_full_text,
                )
                extracted_claims.extend(parsed_chunk_claims)
                break  # Successful extraction

            except (json.JSONDecodeError, ValueError, ValidationError) as err:
                logger.warning(
                    f"[LegalExtractor] Attempt {attempts}/{self.max_retries + 1} failed "
                    f"for chunk_id={chunk.chunk_id!r}: {err}"
                )
                if attempts <= self.max_retries:
                    # Retry with error feedback injected
                    current_prompt = (
                        f"{prompt}\n\n"
                        f"CRITICAL: Your previous response failed validation with error:\n{err}\n"
                        f"Please fix the format and output only a valid JSON array conforming to the specification."
                    )
                else:
                    logger.error(
                        f"[LegalExtractor] All {self.max_retries + 1} attempts exhausted "
                        f"for chunk_id={chunk.chunk_id!r}. Skipping chunk."
                    )

        return extracted_claims

    def _parse_and_verify_items(
        self,
        raw_items: list[dict],
        chunk: Chunk,
        defined_terms: dict[str, str],
        doc_full_text: Optional[str] = None,
    ) -> list[LegalClaim]:
        """Convert raw dicts to LegalClaims, checking span exactness."""
        claims: list[LegalClaim] = []

        for item in raw_items:
            try:
                # 1. Parse claim type
                claim_type = LegalClaimType(item["claim_type"].lower())

                # 2. Extract relative chunk offsets
                rel_start = int(item["char_start"])
                rel_end = int(item["char_end"])
                snippet = str(item.get("text_snippet", "")).strip()

                # Verify snippet against chunk text first
                if rel_start < 0 or rel_end > len(chunk.text) or rel_end <= rel_start:
                    logger.warning(
                        f"[DROPPED CLAIM] Relative offsets [{rel_start}:{rel_end}] "
                        f"out of chunk bounds [0:{len(chunk.text)}]"
                    )
                    continue

                chunk_slice = chunk.text[rel_start:rel_end].strip()
                if snippet != chunk_slice:
                    logger.warning(
                        f"[DROPPED CLAIM] Snippet mismatch in chunk: "
                        f"expected {snippet!r}, found {chunk_slice!r}"
                    )
                    continue

                # 3. Calculate global document offsets
                global_start = chunk.span.char_start + rel_start
                global_end = chunk.span.char_start + rel_end

                # Global document verification if available
                if doc_full_text is not None:
                    doc_slice = doc_full_text[global_start:global_end].strip()
                    if snippet != doc_slice:
                        logger.warning(
                            f"[DROPPED CLAIM] Snippet mismatch in full doc: "
                            f"expected {snippet!r}, found {doc_slice!r}"
                        )
                        continue

                # 4. Construct valid SourceSpan
                span = SourceSpan(
                    doc_id=chunk.doc_id,
                    doc_path=chunk.doc_path,
                    page=chunk.span.page,
                    section=chunk.span.section,
                    char_start=global_start,
                    char_end=global_end,
                    text_snippet=chunk.text[rel_start:rel_end][:500],
                )

                # 5. Attach relevant defined terms
                relevant_terms: dict[str, str] = {}
                for term, defn in defined_terms.items():
                    if term.lower() in snippet.lower() or term.lower() in item.get("raw_text", "").lower():
                        relevant_terms[term] = defn

                claim = LegalClaim(
                    claim_type=claim_type,
                    predicate=str(item["predicate"]),
                    raw_text=str(item["raw_text"]),
                    span=span,
                    parties=list(item.get("parties", [])),
                    defined_terms=relevant_terms,
                    scope_qualifier=item.get("scope_qualifier"),
                    confidence=float(item.get("confidence", 0.95)),
                    extractor=f"llm:{self.provider.__class__.__name__}:{self.prompt_version}",
                )
                claims.append(claim)

            except Exception as err:
                logger.warning(f"[LegalExtractor] Failed to build LegalClaim: {err}")
                continue

        return claims
