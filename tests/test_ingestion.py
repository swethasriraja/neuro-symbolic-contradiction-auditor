"""
Unit tests for document ingestion and chunking.
"""
from __future__ import annotations

import io
from pathlib import Path
import docx
import pypdf
import pytest

from ingestion.chunker import SectionAwareChunker
from ingestion.docx import DocxParser
from ingestion.html import HTMLParser
from ingestion.models import NonExtractableDocumentError
from ingestion.pdf import PDFParser
from ingestion.txt import PlainTextParser
from schemas.chunk import ChunkType


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestPlainTextParserAndChunker:
    def test_parse_and_exact_offsets(self) -> None:
        contract_path = FIXTURES_DIR / "sample_contract.txt"
        parser = PlainTextParser()
        doc = parser.parse_file(contract_path)

        assert doc.doc_id
        assert len(doc.sections) >= 3
        assert any("PAYMENT TERMS" in s.title for s in doc.sections)

        # Chunk the document
        chunker = SectionAwareChunker(chunk_size_chars=400)
        chunks = chunker.chunk_document(doc)

        assert len(chunks) > 0

        # CRITICAL TEST: Exact offset invariant
        for chunk in chunks:
            extracted_slice = doc.full_text[chunk.span.char_start : chunk.span.char_end]
            assert extracted_slice == chunk.text
            assert chunk.doc_id == doc.doc_id
            assert chunk.span.doc_id == doc.doc_id

    def test_no_chunk_crosses_section_boundary(self) -> None:
        contract_path = FIXTURES_DIR / "sample_contract.txt"
        parser = PlainTextParser()
        doc = parser.parse_file(contract_path)
        chunker = SectionAwareChunker(chunk_size_chars=200)
        chunks = chunker.chunk_document(doc)

        for chunk in chunks:
            # Chunk start and end must reside within exactly one section boundary
            matching_sections = [
                s for s in doc.sections
                if s.char_start <= chunk.span.char_start and chunk.span.char_end <= s.char_end
            ]
            assert len(matching_sections) == 1, (
                f"Chunk [{chunk.span.char_start}:{chunk.span.char_end}] crosses section boundaries: "
                f"{chunk.text[:50]}"
            )


class TestHTMLParserAndChunker:
    def test_parse_html_and_tables(self) -> None:
        html_path = FIXTURES_DIR / "sample_financial.html"
        parser = HTMLParser()
        doc = parser.parse_file(html_path)

        assert doc.doc_id
        assert len(doc.tables) == 1
        table = doc.tables[0]
        assert "Segment" in table.headers
        assert len(table.rows) == 3
        assert "520,000,000" in table.to_markdown()

        # Exact offsets test
        chunker = SectionAwareChunker(chunk_size_chars=500)
        chunks = chunker.chunk_document(doc)

        for chunk in chunks:
            assert doc.full_text[chunk.span.char_start : chunk.span.char_end] == chunk.text

        # Verify table chunk type
        table_chunks = [c for c in chunks if c.chunk_type == ChunkType.TABLE_ROW]
        assert len(table_chunks) >= 1


class TestDocxParser:
    def test_docx_creation_and_parsing(self, tmp_path: Path) -> None:
        # Create a synthetic docx
        doc_file = tmp_path / "test.docx"
        d = docx.Document()
        d.add_heading("Section 1: Scope", level=1)
        d.add_paragraph("This is the scope paragraph text.")
        tbl = d.add_table(rows=2, cols=2)
        tbl.cell(0, 0).text = "Metric"
        tbl.cell(0, 1).text = "Value"
        tbl.cell(1, 0).text = "Revenue"
        tbl.cell(1, 1).text = "100M"
        d.save(str(doc_file))

        parser = DocxParser()
        parsed = parser.parse_file(doc_file)

        assert "Section 1: Scope" in parsed.full_text
        assert len(parsed.tables) == 1
        assert parsed.tables[0].headers == ["Metric", "Value"]

        chunker = SectionAwareChunker(chunk_size_chars=300)
        chunks = chunker.chunk_document(parsed)
        for chunk in chunks:
            assert parsed.full_text[chunk.span.char_start : chunk.span.char_end] == chunk.text


class TestPDFParserAndScannedDetection:
    def test_scanned_pdf_error(self, tmp_path: Path) -> None:
        # Create a 1-page PDF with empty text
        pdf_path = tmp_path / "empty.pdf"
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with open(pdf_path, "wb") as f:
            writer.write(f)

        parser = PDFParser()
        with pytest.raises(NonExtractableDocumentError, match="insufficient text"):
            parser.parse_file(pdf_path)
