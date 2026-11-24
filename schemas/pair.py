"""
CandidatePair — a retrieval-flagged pair of claims for contradiction checking.

Produced by the retrieval layer when two claims within the same document are
semantically similar enough (cosine similarity >= threshold) to warrant
symbolic contradiction checking.

Validation rules (enforced at parse time)
------------------------------------------
- claim_a.claim_id != claim_b.claim_id  (no self-pairing)
- claim_a.span.doc_id == claim_b.span.doc_id  (intra-document only; v1 scope)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.claim import Claim


class CandidatePair(BaseModel):
    """A retrieval-flagged pair of claims requiring contradiction analysis."""

    model_config = ConfigDict(frozen=True)

    pair_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Stable UUID4 for this pair."""

    claim_a: Claim
    """First claim in the candidate pair."""

    claim_b: Claim
    """Second claim in the candidate pair. Must differ from claim_a."""

    similarity_score: float = Field(ge=0.0, le=1.0)
    """Cosine similarity score from FAISS (or 1.0 for rule-exact matches)."""

    retrieval_method: str
    """How this pair was surfaced.
    E.g. 'faiss_cosine', 'rule_exact', 'type_match_payment'."""

    flagged_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    metadata: dict[str, Any] = Field(default_factory=dict)
    """Extra context, e.g. {'threshold': 0.85, 'index': 'legal_obligations'}."""

    @model_validator(mode="after")
    def _validate_pair(self) -> "CandidatePair":
        if self.claim_a.claim_id == self.claim_b.claim_id:
            raise ValueError(
                f"claim_a and claim_b must be different claims; "
                f"same claim_id detected: {self.claim_a.claim_id!r}"
            )
        if self.claim_a.span.doc_id != self.claim_b.span.doc_id:
            raise ValueError(
                f"v1 supports intra-document pairs only; "
                f"claim_a.span.doc_id={self.claim_a.span.doc_id!r} != "
                f"claim_b.span.doc_id={self.claim_b.span.doc_id!r}"
            )
        return self
