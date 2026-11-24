"""
Plain text parser for contracts and filings.
"""
from __future__ import annotations

import re
from ingestion.base import BaseParser, compute_doc_id
from ingestion.models import ParsedDocument, SectionNode


class PlainTextParser(BaseParser):
    """Parses plain UTF-8 text files and infers section/heading hierarchy."""

    SECTION_PATTERN = re.compile(
        r"^(?:§+|SECTION|Section|ARTICLE|Article|\d+\.|\b[A-Z\s]{4,}\b)\s*.*$",
        re.MULTILINE,
    )

    def parse_bytes(self, content: bytes, doc_path: str) -> ParsedDocument:
        doc_id = compute_doc_id(content)
        # Canonicalize newlines immediately to prevent offset drift
        text = content.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")

        sections: list[SectionNode] = []
        matches = list(self.SECTION_PATTERN.finditer(text))

        for i, match in enumerate(matches):
            title = match.group(0).strip()
            char_start = match.start()
            char_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            sections.append(
                SectionNode(
                    title=title,
                    level=1,
                    char_start=char_start,
                    char_end=char_end,
                    page=1,
                )
            )

        # If no explicit sections detected, treat entire document as root section
        if not sections and text:
            sections.append(
                SectionNode(
                    title="Document Root",
                    level=0,
                    char_start=0,
                    char_end=len(text),
                    page=1,
                )
            )

        page_offsets = [(1, 0, len(text))] if text else []

        return ParsedDocument(
            doc_id=doc_id,
            doc_path=doc_path,
            full_text=text,
            sections=sections,
            tables=[],
            page_offsets=page_offsets,
        )
