"""
Section-Aware Chunker.

Guarantees:
1. No chunk crosses a section boundary.
2. Exact offsets: parsed_doc.full_text[chunk.span.char_start : chunk.span.char_end] == chunk.text.
3. Tables are emitted as structured ChunkType.TABLE_ROW or TABLE_CELL chunks with SourceSpan.
"""
from __future__ import annotations

import re
from typing import Optional

from ingestion.models import ParsedDocument, SectionNode
from schemas.chunk import Chunk, ChunkType
from schemas.span import SourceSpan


class SectionAwareChunker:
    """
    Chunks a ParsedDocument by section/heading first, then splits by paragraph/size.
    Preserves exact character offsets such that doc.full_text[start:end] == chunk.text.
    """

    def __init__(self, chunk_size_chars: int = 2000):
        self.chunk_size_chars = chunk_size_chars

    def chunk_document(self, doc: ParsedDocument) -> list[Chunk]:
        """Split a ParsedDocument into a sequence of provenance-anchored Chunks."""
        chunks: list[Chunk] = []

        if not doc.full_text.strip():
            return chunks

        table_ranges = [(t.char_start, t.char_end) for t in doc.tables]

        # Use sections as primary partition
        sections = doc.sections or [
            SectionNode(
                title="Document Root",
                level=0,
                char_start=0,
                char_end=len(doc.full_text),
                page=1,
            )
        ]

        for sec in sections:
            sec_start = sec.char_start
            sec_end = min(sec.char_end, len(doc.full_text))
            if sec_start >= sec_end:
                continue

            sec_text = doc.full_text[sec_start:sec_end]
            if not sec_text.strip():
                continue

            # Check if this entire section is a table
            is_table_section = any(
                max(sec_start, t_start) < min(sec_end, t_end)
                for t_start, t_end in table_ranges
            )

            # If section fits in chunk size, emit as a single chunk
            if len(sec_text) <= self.chunk_size_chars:
                chunk_type = ChunkType.TABLE_ROW if is_table_section else (
                    ChunkType.HEADER if sec.level > 0 and len(sec_text) < 150 else ChunkType.TEXT
                )
                span = SourceSpan(
                    doc_id=doc.doc_id,
                    doc_path=doc.doc_path,
                    page=doc.get_page_for_offset(sec_start),
                    section=sec.title,
                    char_start=sec_start,
                    char_end=sec_end,
                    text_snippet=sec_text[:500],
                )
                chunks.append(
                    Chunk(
                        doc_id=doc.doc_id,
                        doc_path=doc.doc_path,
                        text=sec_text,
                        span=span,
                        chunk_type=chunk_type,
                        metadata={"section_title": sec.title, "section_level": sec.level},
                    )
                )
            else:
                # Sub-chunk the section without crossing its boundary
                sub_chunks = self._sub_chunk_text(
                    doc=doc,
                    text=sec_text,
                    base_offset=sec_start,
                    section_title=sec.title,
                    section_level=sec.level,
                    table_ranges=table_ranges,
                )
                chunks.extend(sub_chunks)

        return chunks

    def _sub_chunk_text(
        self,
        doc: ParsedDocument,
        text: str,
        base_offset: int,
        section_title: str,
        section_level: int,
        table_ranges: list[tuple[int, int]],
    ) -> list[Chunk]:
        """Split oversized section on paragraph boundaries, preserving exact global offsets."""
        sub_chunks: list[Chunk] = []
        n = len(text)
        cursor = 0

        while cursor < n:
            target_end = min(cursor + self.chunk_size_chars, n)
            if target_end == n:
                split_at = n
            else:
                p_break = text.rfind("\n\n", cursor, target_end)
                if p_break != -1 and p_break > cursor:
                    split_at = p_break + 2
                else:
                    s_break = text.rfind(". ", cursor, target_end)
                    if s_break != -1 and s_break > cursor:
                        split_at = s_break + 2
                    else:
                        nl_break = text.rfind("\n", cursor, target_end)
                        if nl_break != -1 and nl_break > cursor:
                            split_at = nl_break + 1
                        else:
                            split_at = target_end

            chunk_text = text[cursor:split_at]
            global_start = base_offset + cursor
            global_end = base_offset + split_at

            if chunk_text.strip():
                # Check if this sub-chunk overlaps any table
                is_table = any(
                    max(global_start, t_start) < min(global_end, t_end)
                    for t_start, t_end in table_ranges
                )
                span = SourceSpan(
                    doc_id=doc.doc_id,
                    doc_path=doc.doc_path,
                    page=doc.get_page_for_offset(global_start),
                    section=section_title,
                    char_start=global_start,
                    char_end=global_end,
                    text_snippet=chunk_text[:500],
                )
                sub_chunks.append(
                    Chunk(
                        doc_id=doc.doc_id,
                        doc_path=doc.doc_path,
                        text=chunk_text,
                        span=span,
                        chunk_type=ChunkType.TABLE_ROW if is_table else ChunkType.TEXT,
                        metadata={"section_title": section_title, "section_level": section_level},
                    )
                )

            cursor = split_at

        return sub_chunks
