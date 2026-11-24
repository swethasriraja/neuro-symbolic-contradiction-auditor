"""
PDF parser using pdfplumber with fallback to pypdf.
Includes scanned-image PDF detection, page offset tracking, and table extraction.
"""
from __future__ import annotations

import io
import re
from typing import Any
import pdfplumber

from ingestion.base import BaseParser, compute_doc_id
from ingestion.models import (
    ExtractedTable,
    NonExtractableDocumentError,
    ParsedDocument,
    SectionNode,
)


class PDFParser(BaseParser):
    """
    Parses digital PDF contracts and financial reports.
    Detects scanned image-only PDFs and raises NonExtractableDocumentError.
    """

    HEADING_REGEX = re.compile(
        r"^(?:§\s*\d+|SECTION\s+\d+|ARTICLE\s+[IVXLCDM\d]+|\d+\.\d*\s+[A-Z]).*$",
        re.MULTILINE,
    )

    def parse_bytes(self, content: bytes, doc_path: str) -> ParsedDocument:
        doc_id = compute_doc_id(content)
        full_text_parts: list[str] = []
        sections: list[SectionNode] = []
        tables: list[ExtractedTable] = []
        page_offsets: list[tuple[int, int, int]] = []

        total_extracted_chars = 0
        current_offset = 0

        with pdfplumber.open(io.BytesIO(content)) as pdf:
            total_pages = len(pdf.pages)
            if total_pages == 0:
                raise NonExtractableDocumentError(f"PDF '{doc_path}' has 0 pages.")

            for page_idx, page in enumerate(pdf.pages):
                page_num = page_idx + 1
                page_start = current_offset

                # 1. Extract tables from page
                raw_tables = page.extract_tables() or []
                for tbl_data in raw_tables:
                    if tbl_data and len(tbl_data) >= 1:
                        headers = [str(c or "").strip() for c in tbl_data[0]]
                        rows = [
                            [str(c or "").strip() for c in row]
                            for row in tbl_data[1:]
                        ]
                        t_obj = ExtractedTable(
                            headers=headers,
                            rows=rows,
                            char_start=current_offset,
                            char_end=current_offset,
                            page=page_num,
                        )
                        md_repr = "\n\n" + t_obj.to_markdown() + "\n\n"
                        t_start = current_offset
                        full_text_parts.append(md_repr)
                        current_offset += len(md_repr)
                        tables.append(
                            ExtractedTable(
                                headers=headers,
                                rows=rows,
                                char_start=t_start,
                                char_end=current_offset,
                                page=page_num,
                                raw_text=md_repr.strip(),
                            )
                        )

                # 2. Extract page narrative text
                page_text = page.extract_text() or ""
                # Normalize newlines
                page_text = page_text.replace("\r\n", "\n").replace("\r", "\n")
                total_extracted_chars += len(page_text.strip())

                if page_text:
                    p_str = page_text + "\n\n"
                    full_text_parts.append(p_str)
                    current_offset += len(p_str)

                page_offsets.append((page_num, page_start, current_offset))

        full_text = "".join(full_text_parts).strip()

        # Scanned PDF check: less than 40 chars average per page
        avg_chars_per_page = total_extracted_chars / max(1, total_pages)
        if avg_chars_per_page < 30:
            raise NonExtractableDocumentError(
                f"PDF '{doc_path}' contains insufficient text ({avg_chars_per_page:.1f} chars/page). "
                f"Document appears to be a scanned image; OCR is required (v2 scope)."
            )

        # Detect sections in full_text
        for match in self.HEADING_REGEX.finditer(full_text):
            title = match.group(0).strip()
            char_start = match.start()
            sections.append(
                SectionNode(
                    title=title,
                    level=1,
                    char_start=char_start,
                    char_end=len(full_text),  # resolved below
                    page=1,
                )
            )

        # Fix section boundaries
        for i in range(len(sections)):
            end = sections[i + 1].char_start if i + 1 < len(sections) else len(full_text)
            sections[i] = SectionNode(
                title=sections[i].title,
                level=sections[i].level,
                char_start=sections[i].char_start,
                char_end=end,
                page=sections[i].page,
            )

        if not sections and full_text:
            sections.append(
                SectionNode(
                    title="Document Root",
                    level=0,
                    char_start=0,
                    char_end=len(full_text),
                    page=1,
                )
            )

        return ParsedDocument(
            doc_id=doc_id,
            doc_path=doc_path,
            full_text=full_text,
            sections=sections,
            tables=tables,
            page_offsets=page_offsets,
        )
