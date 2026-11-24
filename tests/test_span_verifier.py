"""
Unit tests for strict span verification.
Verifies that fabricated or mismatched citations are unconditionally rejected.
"""
from __future__ import annotations

import pytest

from extraction.verifier import SpanVerifier
from schemas.claim import LegalClaim, LegalClaimType
from schemas.span import SourceSpan

DOC_TEXT = (
    "MASTER SERVICES AGREEMENT\n\n"
    "§ 2. PAYMENT TERMS\n"
    "Payment shall be due within thirty (30) days following receipt of an invoice.\n"
    "Licensee shall pay an annual fee of $100,000.\n"
)


def make_span(start: int, end: int, snippet: str) -> SourceSpan:
    return SourceSpan(
        doc_id="a" * 64,
        doc_path="contract.txt",
        char_start=start,
        char_end=end,
        text_snippet=snippet,
    )


class TestSpanVerifier:
    def test_exact_span_valid(self) -> None:
        target = "Payment shall be due within thirty (30) days"
        start = DOC_TEXT.index(target)
        end = start + len(target)
        span = make_span(start, end, target)

        is_valid, reason = SpanVerifier.verify_span(DOC_TEXT, span)
        assert is_valid is True
        assert reason is None

    def test_fabricated_span_mismatched_text(self) -> None:
        target = "Payment shall be due within thirty (30) days"
        start = DOC_TEXT.index(target)
        end = start + len(target)
        # Fabricated snippet text that does not match the actual slice
        fake_span = make_span(start, end, "Payment shall be due within fifteen (15) days")

        is_valid, reason = SpanVerifier.verify_span(DOC_TEXT, fake_span)
        assert is_valid is False
        assert "mismatch" in reason.lower()

    def test_fabricated_span_wrong_offsets(self) -> None:
        target = "Payment shall be due within thirty (30) days"
        # Correct snippet, but wrong shifted offsets
        wrong_span = make_span(0, len(target), target)

        is_valid, reason = SpanVerifier.verify_span(DOC_TEXT, wrong_span)
        assert is_valid is False
        assert "mismatch" in reason.lower()

    def test_span_out_of_bounds_end(self) -> None:
        span = make_span(0, len(DOC_TEXT) + 50, "test")
        is_valid, reason = SpanVerifier.verify_span(DOC_TEXT, span)
        assert is_valid is False
        assert "exceeds" in reason.lower()

    def test_filter_valid_claims_drops_fabricated_spans(self) -> None:
        # Create one authentic claim and one fabricated claim
        real_text = "Licensee shall pay an annual fee of $100,000."
        real_start = DOC_TEXT.index(real_text)
        real_span = make_span(real_start, real_start + len(real_text), real_text)

        valid_claim = LegalClaim(
            claim_type=LegalClaimType.AMOUNT,
            predicate="annual_fee(Licensee, 100000, USD)",
            raw_text=real_text,
            span=real_span,
            confidence=0.99,
            extractor="test",
        )

        fabricated_span = make_span(real_start, real_start + len(real_text), "Fabricated text")
        invalid_claim = LegalClaim(
            claim_type=LegalClaimType.AMOUNT,
            predicate="annual_fee(Licensee, 999999, USD)",
            raw_text=real_text,
            span=fabricated_span,
            confidence=0.99,
            extractor="test",
        )

        filtered = SpanVerifier.filter_valid_claims(DOC_TEXT, [valid_claim, invalid_claim])
        assert len(filtered) == 1
        assert filtered[0].claim_id == valid_claim.claim_id
