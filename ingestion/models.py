"""
Data models for the document ingestion pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


class NonExtractableDocumentError(Exception):
    """Raised when a document has no readable digital text layer (e.g. scanned image PDF)."""
    pass


@dataclass(frozen=True)
class SectionNode:
    """A detected heading or structural section within a document."""
    title: str
    level: int
    char_start: int
    char_end: int
    page: Optional[int] = None


@dataclass(frozen=True)
class ExtractedTable:
    """A structured table extracted from a document."""
    headers: list[str]
    rows: list[list[str]]
    char_start: int
    char_end: int
    page: Optional[int] = None
    section: Optional[str] = None
    caption: Optional[str] = None
    raw_text: str = ""

    def to_markdown(self) -> str:
        """Render table as markdown string for LLM readability."""
        if not self.headers and not self.rows:
            return ""
        lines: list[str] = []
        if self.caption:
            lines.append(f"### Table: {self.caption}")
        cols = self.headers if self.headers else [f"Col {i+1}" for i in range(len(self.rows[0]) if self.rows else 0)]
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
        for row in self.rows:
            # pad or truncate row to cols length
            padded = row + [""] * (len(cols) - len(row))
            lines.append("| " + " | ".join(padded[:len(cols)]) + " |")
        return "\n".join(lines)


@dataclass
class ParsedDocument:
    """Canonical representation of a parsed document with exact text offsets."""
    doc_id: str
    doc_path: str
    full_text: str
    sections: list[SectionNode] = field(default_factory=list)
    tables: list[ExtractedTable] = field(default_factory=list)
    page_offsets: list[tuple[int, int, int]] = field(default_factory=list)
    # page_offsets: list of (page_number, char_start, char_end)

    def get_page_for_offset(self, char_offset: int) -> Optional[int]:
        """Find the 1-indexed page containing char_offset."""
        for page_num, start, end in self.page_offsets:
            if start <= char_offset < end:
                return page_num
        return self.page_offsets[-1][0] if self.page_offsets else None

    def get_section_for_offset(self, char_offset: int) -> Optional[str]:
        """Find the section containing char_offset (deepest level)."""
        matching: list[SectionNode] = []
        for sec in self.sections:
            if sec.char_start <= char_offset < sec.char_end:
                matching.append(sec)
        if matching:
            # return deepest or most specific section
            matching.sort(key=lambda s: s.char_start, reverse=True)
            return matching[0].title
        return None
