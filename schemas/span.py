"""
SourceSpan — provenance anchor.

Every claim, chunk, and finding must carry a SourceSpan.
Malformed spans (inverted offsets, negative start, snippet > 500 chars)
are rejected at Pydantic validation time — not at runtime.

Design note
-----------
doc_id is the SHA-256 hex digest of the source file bytes.
The schema stores it; ingestion (Step 2) computes and injects it.
The schema does NOT re-verify the hash — that is ingestion's responsibility.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, model_validator


class SourceSpan(BaseModel):
    """Precise location of a text excerpt within a source document."""

    model_config = ConfigDict(frozen=True)

    doc_id: str
    """SHA-256 hex digest of the source file bytes (64 hex chars).
    Computed at ingestion; stored here for integrity tracking."""

    doc_path: str
    """Human-readable filename or relative path, e.g. 'contracts/msa_v3.pdf'.
    Stored alongside doc_id for readability in logs and UI."""

    page: Optional[int] = None
    """1-indexed page number. None for plain-text or HTML sources."""

    section: Optional[str] = None
    """Clause or section reference, e.g. '§ 4.2(b)', 'Note 7', 'MD&A'."""

    char_start: int
    """Inclusive, 0-indexed character offset over the full document text."""

    char_end: int
    """Exclusive character offset. Invariant: char_end > char_start."""

    text_snippet: str
    """Verbatim excerpt from the source text. Max 500 characters.
    Must be a substring of the original document at [char_start:char_end]
    (verified by ingestion, not enforced here)."""

    @model_validator(mode="after")
    def _validate_offsets_and_snippet(self) -> "SourceSpan":
        if self.char_start < 0:
            raise ValueError(
                f"char_start must be >= 0, got {self.char_start}"
            )
        if self.char_end <= self.char_start:
            raise ValueError(
                f"char_end ({self.char_end}) must be strictly greater than "
                f"char_start ({self.char_start})"
            )
        if len(self.text_snippet) > 500:
            raise ValueError(
                f"text_snippet must be <= 500 characters, "
                f"got {len(self.text_snippet)}"
            )
        return self
