"""
Unit tests for legal and financial claim extractors using MockLLMProvider.
Guarantees zero network calls and asserts full telemetry logging and retry behavior.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from extraction.defined_terms import DefinedTermExtractor
from extraction.financial import FinancialExtractor
from extraction.legal import LegalExtractor
from extraction.mock_provider import MockLLMProvider
from ingestion.chunker import SectionAwareChunker
from ingestion.txt import PlainTextParser
from schemas.chunk import Chunk, ChunkType
from schemas.claim import FinancialMetric, LegalClaimType, SourceType
from schemas.span import SourceSpan

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestDefinedTermsExtraction:
    def test_regex_and_document_glossary(self) -> None:
        contract_path = FIXTURES_DIR / "sample_contract.txt"
        parser = PlainTextParser()
        doc = parser.parse_file(contract_path)

        extractor = DefinedTermExtractor()
        terms = extractor.extract_from_document(doc)

        assert "Business Day" in terms
        assert "New York" in terms["Business Day"]
        assert "Effective Date" in terms
        assert "January 1, 2024" in terms["Effective Date"]


class TestLegalExtractorWithMock:
    def test_successful_extraction_and_telemetry(self) -> None:
        chunk_text = "Payment shall be due within thirty (30) days following receipt of an invoice."
        span = SourceSpan(
            doc_id="a" * 64,
            doc_path="contract.txt",
            char_start=100,
            char_end=100 + len(chunk_text),
            text_snippet=chunk_text,
        )
        chunk = Chunk(
            doc_id="a" * 64,
            doc_path="contract.txt",
            text=chunk_text,
            span=span,
            chunk_type=ChunkType.TEXT,
        )

        # Mock response matching exact relative slice
        mock_payload = [
            {
                "claim_type": "obligation",
                "predicate": "payment_due(Licensee, 30, days)",
                "raw_text": chunk_text,
                "char_start": 0,
                "char_end": len(chunk_text),
                "text_snippet": chunk_text,
                "parties": ["Licensee"],
                "confidence": 0.95,
            }
        ]
        provider = MockLLMProvider(default_response=json.dumps(mock_payload))

        extractor = LegalExtractor(provider=provider, max_retries=1)
        claims = extractor.extract_claims_from_chunk(chunk, defined_terms={"Business Day": "Mon-Fri"})

        assert len(claims) == 1
        claim = claims[0]
        assert claim.claim_type == LegalClaimType.OBLIGATION
        assert claim.span.char_start == 100
        assert claim.span.char_end == 100 + len(chunk_text)
        assert claim.span.text_snippet == chunk_text

        # Verify telemetry was logged
        assert len(provider.call_history) == 1
        call = provider.call_history[0]
        assert call["model"] == "mock-provider-v1"
        assert call["prompt_tokens"] > 0
        assert call["completion_tokens"] > 0
        assert isinstance(call["cost_usd"], Decimal)

    def test_retry_on_malformed_json(self) -> None:
        chunk_text = "Payment shall be due within thirty (30) days."
        span = SourceSpan(
            doc_id="a" * 64,
            doc_path="contract.txt",
            char_start=0,
            char_end=len(chunk_text),
            text_snippet=chunk_text,
        )
        chunk = Chunk(
            doc_id="a" * 64,
            doc_path="contract.txt",
            text=chunk_text,
            span=span,
            chunk_type=ChunkType.TEXT,
        )

        provider = MockLLMProvider()
        # First attempt: invalid JSON string; Second attempt: valid JSON
        provider.queue_response("NOT VALID JSON {{")
        valid_payload = [
            {
                "claim_type": "deadline",
                "predicate": "payment_deadline(30, days)",
                "raw_text": chunk_text,
                "char_start": 0,
                "char_end": len(chunk_text),
                "text_snippet": chunk_text,
                "confidence": 0.90,
            }
        ]
        provider.queue_response(json.dumps(valid_payload))

        extractor = LegalExtractor(provider=provider, max_retries=2)
        claims = extractor.extract_claims_from_chunk(chunk)

        assert len(claims) == 1
        assert len(provider.call_history) == 2
        # Verify second call received error feedback
        assert "previous response failed validation" in provider.call_history[1]["prompt"]

    def test_drop_claim_on_fabricated_snippet(self) -> None:
        chunk_text = "Payment shall be due within thirty (30) days."
        span = SourceSpan(
            doc_id="a" * 64,
            doc_path="contract.txt",
            char_start=0,
            char_end=len(chunk_text),
            text_snippet=chunk_text,
        )
        chunk = Chunk(
            doc_id="a" * 64,
            doc_path="contract.txt",
            text=chunk_text,
            span=span,
            chunk_type=ChunkType.TEXT,
        )

        # Output with fabricated text snippet that does not match chunk[char_start:char_end]
        fabricated_payload = [
            {
                "claim_type": "obligation",
                "predicate": "payment_due(Licensee, 15, days)",
                "raw_text": "Payment shall be due within fifteen (15) days.",
                "char_start": 0,
                "char_end": 10,
                "text_snippet": "Payment shall be due within fifteen (15) days.",
                "confidence": 0.95,
            }
        ]
        provider = MockLLMProvider(default_response=json.dumps(fabricated_payload))
        extractor = LegalExtractor(provider=provider, max_retries=0)
        claims = extractor.extract_claims_from_chunk(chunk)

        # Claim must be dropped immediately!
        assert len(claims) == 0


class TestFinancialExtractorWithMock:
    def test_narrative_and_table_extraction(self) -> None:
        chunk_text = "Total consolidated revenue was $500,000,000 for fiscal year 2023."
        span = SourceSpan(
            doc_id="f" * 64,
            doc_path="filing.html",
            char_start=200,
            char_end=200 + len(chunk_text),
            text_snippet=chunk_text,
        )
        chunk = Chunk(
            doc_id="f" * 64,
            doc_path="filing.html",
            text=chunk_text,
            span=span,
            chunk_type=ChunkType.TEXT,
        )

        mock_payload = [
            {
                "metric": "revenue",
                "value": "500000000",
                "unit": "USD",
                "period": "2023-01-01/2023-12-31",
                "entity": "Acme Corp",
                "source_type": "narrative",
                "predicate": "revenue(Acme_Corp, FY2023, 500000000, USD)",
                "raw_text": chunk_text,
                "char_start": 0,
                "char_end": len(chunk_text),
                "text_snippet": chunk_text,
                "confidence": 0.98,
            }
        ]
        provider = MockLLMProvider(default_response=json.dumps(mock_payload))
        extractor = FinancialExtractor(provider=provider)

        claims = extractor.extract_claims_from_chunk(chunk)
        assert len(claims) == 1
        claim = claims[0]
        assert claim.metric == FinancialMetric.REVENUE
        assert claim.value == Decimal("500000000")
        assert isinstance(claim.value, Decimal)
        assert claim.source_type == SourceType.NARRATIVE
        assert claim.span.char_start == 200
        assert claim.span.char_end == 200 + len(chunk_text)
