"""
Financial Claim Extractor with retry loop and strict span verification.
Supports narrative prose and structured table chunks.
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Optional

from pydantic import ValidationError

from extraction.prompt_loader import load_prompt
from extraction.provider import LLMProvider, LLMResponse
from schemas.chunk import Chunk, ChunkType
from schemas.claim import FinancialClaim, FinancialMetric, SourceType
from schemas.span import SourceSpan

logger = logging.getLogger(__name__)


class FinancialExtractor:
    """
    Extracts FinancialClaims from financial report chunks (narrative and table),
    enforcing Decimal precision, Pydantic validation, retry loops, and span verification.
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
        doc_full_text: Optional[str] = None,
    ) -> list[FinancialClaim]:
        """
        Extract all FinancialClaims from a financial text or table chunk.

        Args:
            chunk: Input Chunk.
            doc_full_text: Full document text (for global span verification).

        Returns:
            List of verified FinancialClaims.
        """
        source_type = (
            SourceType.TABLE
            if chunk.chunk_type in (ChunkType.TABLE_ROW, ChunkType.TABLE_CELL)
            else SourceType.NARRATIVE
        )

        prompt = load_prompt(
            "financial",
            version=self.prompt_version,
            chunk_text=chunk.text,
            source_type=source_type.value,
        )

        attempts = 0
        current_prompt = prompt
        extracted_claims: list[FinancialClaim] = []

        while attempts <= self.max_retries:
            attempts += 1
            response: LLMResponse = self.provider.generate(
                prompt=current_prompt,
                response_format="json",
            )

            raw_text = response.text.strip()
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
                    if isinstance(raw_items, dict):
                        if "claims" in raw_items and isinstance(raw_items["claims"], list):
                            raw_items = raw_items["claims"]
                        elif "financial_claims" in raw_items and isinstance(raw_items["financial_claims"], list):
                            raw_items = raw_items["financial_claims"]
                        elif "items" in raw_items and isinstance(raw_items["items"], list):
                            raw_items = raw_items["items"]
                        elif "data" in raw_items and isinstance(raw_items["data"], list):
                            raw_items = raw_items["data"]
                        elif "metric" in raw_items:
                            raw_items = [raw_items]
                        else:
                            raw_items = []
                    else:
                        raise ValueError(f"Expected JSON array of claims, got {type(raw_items).__name__}")

                parsed_chunk_claims = self._parse_and_verify_items(
                    raw_items=raw_items,
                    chunk=chunk,
                    default_source_type=source_type,
                    doc_full_text=doc_full_text,
                )
                extracted_claims.extend(parsed_chunk_claims)
                break

            except (json.JSONDecodeError, ValueError, ValidationError) as err:
                logger.warning(
                    f"[FinancialExtractor] Attempt {attempts}/{self.max_retries + 1} failed "
                    f"for chunk_id={chunk.chunk_id!r}: {err}"
                )
                if attempts <= self.max_retries:
                    current_prompt = (
                        f"{prompt}\n\n"
                        f"CRITICAL: Your previous response failed validation with error:\n{err}\n"
                        f"Please fix the format and output only a valid JSON array conforming to the specification."
                    )
                else:
                    logger.error(
                        f"[FinancialExtractor] All {self.max_retries + 1} attempts exhausted "
                        f"for chunk_id={chunk.chunk_id!r}. Skipping chunk."
                    )

        return extracted_claims

    def _parse_and_verify_items(
        self,
        raw_items: list[dict],
        chunk: Chunk,
        default_source_type: SourceType,
        doc_full_text: Optional[str] = None,
    ) -> list[FinancialClaim]:
        """Convert raw dicts to FinancialClaims, checking Decimal and span exactness."""
        claims: list[FinancialClaim] = []

        for item in raw_items:
            try:
                metric = FinancialMetric(item["metric"].lower())

                # Exact numeric value conversion to Decimal
                val_raw = item.get("value")
                val_decimal: Optional[Decimal] = None
                if val_raw is not None and str(val_raw).strip() != "":
                    cleaned_val = (
                        str(val_raw)
                        .replace("$", "")
                        .replace(",", "")
                        .replace("€", "")
                        .replace("£", "")
                        .strip()
                    )
                    try:
                        val_decimal = Decimal(cleaned_val)
                    except InvalidOperation:
                        val_decimal = None

                # Relative offsets
                rel_start = int(item["char_start"])
                rel_end = int(item["char_end"])
                snippet = str(item.get("text_snippet", "")).strip()

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

                global_start = chunk.span.char_start + rel_start
                global_end = chunk.span.char_start + rel_end

                if doc_full_text is not None:
                    doc_slice = doc_full_text[global_start:global_end].strip()
                    if snippet != doc_slice:
                        logger.warning(
                            f"[DROPPED CLAIM] Snippet mismatch in full doc: "
                            f"expected {snippet!r}, found {doc_slice!r}"
                        )
                        continue

                span = SourceSpan(
                    doc_id=chunk.doc_id,
                    doc_path=chunk.doc_path,
                    page=chunk.span.page,
                    section=chunk.span.section,
                    char_start=global_start,
                    char_end=global_end,
                    text_snippet=chunk.text[rel_start:rel_end][:500],
                )

                st_val = item.get("source_type")
                source_type = (
                    SourceType(st_val.lower())
                    if st_val and st_val.lower() in [s.value for s in SourceType]
                    else default_source_type
                )

                claim = FinancialClaim(
                    metric=metric,
                    value=val_decimal,
                    unit=item.get("unit"),
                    period=item.get("period"),
                    entity=item.get("entity"),
                    source_type=source_type,
                    predicate=str(item["predicate"]),
                    raw_text=str(item["raw_text"]),
                    span=span,
                    confidence=float(item.get("confidence", 0.95)),
                    extractor=f"llm:{self.provider.__class__.__name__}:{self.prompt_version}",
                )
                claims.append(claim)

            except Exception as err:
                logger.warning(f"[FinancialExtractor] Failed to build FinancialClaim: {err}")
                continue

        return claims
