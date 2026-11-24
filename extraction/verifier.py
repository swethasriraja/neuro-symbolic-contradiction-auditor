"""
Strict span verification.

NON-NEGOTIABLE PRINCIPLE:
Every cited span must be verified to exist in the source text at the cited offsets.
Never fabricate citations. Never repair spans silently.
Drop and log any claim that fails verification.
"""
from __future__ import annotations

import logging
from typing import Optional

from schemas.claim import Claim
from schemas.span import SourceSpan

logger = logging.getLogger(__name__)


class SpanVerificationError(Exception):
    """Raised when a cited span fails exact textual matching."""
    pass


class SpanVerifier:
    """Verifies that a SourceSpan exactly matches the underlying document text."""

    @staticmethod
    def verify_span(text: str, span: SourceSpan) -> tuple[bool, Optional[str]]:
        """
        Verify that span.text_snippet exactly matches text[span.char_start:span.char_end].

        Args:
            text: Full text buffer (or chunk text if verifying in local coordinates).
            span: The SourceSpan to test.

        Returns:
            (True, None) if verified; (False, reason_str) if mismatch or out of bounds.
        """
        if span.char_start < 0:
            return False, f"char_start ({span.char_start}) is negative"

        if span.char_end > len(text):
            return (
                False,
                f"char_end ({span.char_end}) exceeds text length ({len(text)})",
            )

        if span.char_end <= span.char_start:
            return (
                False,
                f"char_end ({span.char_end}) <= char_start ({span.char_start})",
            )

        actual_slice = text[span.char_start : span.char_end]

        if actual_slice != span.text_snippet:
            return (
                False,
                f"Text mismatch at [{span.char_start}:{span.char_end}]: "
                f"expected '{span.text_snippet}', found '{actual_slice}'",
            )

        return True, None

    @classmethod
    def verify_claim(cls, doc_text: str, claim: Claim) -> tuple[bool, Optional[str]]:
        """Verify the span attached to a Claim against document text."""
        return cls.verify_span(doc_text, claim.span)

    @classmethod
    def filter_valid_claims(
        cls,
        doc_text: str,
        claims: list[Claim],
    ) -> list[Claim]:
        """
        Filter claims, retaining only those whose spans are verified against doc_text.
        Logs dropped claims with explicit rejection details. Never repairs silently.
        """
        verified: list[Claim] = []
        for claim in claims:
            is_valid, reason = cls.verify_claim(doc_text, claim)
            if is_valid:
                verified.append(claim)
            else:
                logger.warning(
                    f"[DROPPED CLAIM] claim_id={claim.claim_id!r} "
                    f"type={getattr(claim, 'claim_type', getattr(claim, 'metric', 'unknown'))} "
                    f"span=[{claim.span.char_start}:{claim.span.char_end}] "
                    f"REASON: {reason}"
                )
        return verified
