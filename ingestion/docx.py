"""
DOCX parser for contracts and filings using python-docx.
Extracts paragraph styles, heading hierarchy, and native tables.
"""
from __future__ import annotations

import io
from docx import Document
from docx.table import Table as DocxTable
from docx.text.paragraph import Paragraph as DocxParagraph
from ingestion.base import BaseParser, compute_doc_id
from ingestion.models import ExtractedTable, ParsedDocument, SectionNode


class DocxParser(BaseParser):
    """Parses Microsoft Word (.docx) documents."""

    def parse_bytes(self, content: bytes, doc_path: str) -> ParsedDocument:
        doc_id = compute_doc_id(content)
        doc = Document(io.BytesIO(content))

        full_text_parts: list[str] = []
        sections: list[SectionNode] = []
        tables: list[ExtractedTable] = []
        current_offset = 0

        # Iterate elements in document body order
        for child in doc.element.body:
            tag_name = child.tag.split("}")[-1] if "}" in child.tag else child.tag

            if tag_name == "p":
                para = DocxParagraph(child, doc)
                text = para.text.strip()
                if not text:
                    continue

                style_name = para.style.name.lower() if para.style else ""
                is_heading = "heading" in style_name or "title" in style_name
                level = 1
                if is_heading:
                    for char in style_name:
                        if char.isdigit():
                            level = int(char)
                            break

                p_str = f"{text}\n\n"
                start = current_offset
                full_text_parts.append(p_str)
                current_offset += len(p_str)

                if is_heading:
                    sections.append(
                        SectionNode(
                            title=text,
                            level=level,
                            char_start=start,
                            char_end=start + len(p_str),
                            page=1,
                        )
                    )

            elif tag_name == "tbl":
                tbl = DocxTable(child, doc)
                rows_data: list[list[str]] = []
                for row in tbl.rows:
                    row_data = [cell.text.strip() for cell in row.cells]
                    if any(row_data):
                        rows_data.append(row_data)

                if rows_data:
                    headers = rows_data[0]
                    rows = rows_data[1:] if len(rows_data) > 1 else []
                    temp_tbl = ExtractedTable(
                        headers=headers,
                        rows=rows,
                        char_start=current_offset,
                        char_end=current_offset,
                        page=1,
                        section=sections[-1].title if sections else None,
                    )
                    md_repr = "\n\n" + temp_tbl.to_markdown() + "\n\n"
                    start = current_offset
                    full_text_parts.append(md_repr)
                    current_offset += len(md_repr)
                    end = current_offset

                    tables.append(
                        ExtractedTable(
                            headers=headers,
                            rows=rows,
                            char_start=start,
                            char_end=end,
                            page=1,
                            section=sections[-1].title if sections else None,
                            raw_text=md_repr.strip(),
                        )
                    )

        full_text = "".join(full_text_parts).strip()

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
            page_offsets=[(1, 0, len(full_text))] if full_text else [],
        )
