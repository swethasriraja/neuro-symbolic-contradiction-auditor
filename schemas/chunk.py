"""
Chunk — the ingestion unit.

One Chunk represents a semantically coherent text window extracted from a document:
a paragraph, table row, section header + body, footnote, or list item.
Chunks feed both the embedding retrieval index and the claim extraction pipeline.

Validation rules (enforced at parse time)
------------------------------------------
- text must be 1–4 096 characters
- chunk.doc_id must equal chunk.span.doc_id  (consistency guard)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.span import SourceSpan


class ChunkType(str, Enum):
    TEXT = "text"
    TABLE_ROW = "table_row"
    TABLE_CELL = "table_cell"
    HEADER = "header"
    FOOTNOTE = "footnote"
    LIST_ITEM = "list_item"


class Chunk(BaseModel):
    """A document segment produced by the ingestion pipeline."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Stable UUID4. Set once at ingestion; never mutated."""

    doc_id: str
    """SHA-256 of the source file. Must equal span.doc_id."""

    doc_path: str
    """Human-readable filename, e.g. 'contracts/msa_v3.pdf'."""

    text: str
    """Raw extracted text. 1–4 096 characters (enforced by validator)."""

    span: SourceSpan
    """Precise location of this chunk within the source document."""

    chunk_type: ChunkType
    """Structural classification of this text window."""

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Arbitrary ingestion context, e.g. table column headers, surrounding section title."""

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @model_validator(mode="after")
    def _validate_text_and_consistency(self) -> "Chunk":
        if len(self.text) == 0:
            raise ValueError("text must not be empty")
        if len(self.text) > 4096:
            raise ValueError(
                f"text must be <= 4 096 characters, got {len(self.text)}"
            )
        if self.doc_id != self.span.doc_id:
            raise ValueError(
                f"chunk.doc_id '{self.doc_id}' must match "
                f"chunk.span.doc_id '{self.span.doc_id}'"
            )
        return self
