"""
HTML parser for SEC EDGAR filings and financial reports.
Extracts normalized narrative text and structured tables with exact offsets.
"""
from __future__ import annotations

import re
from bs4 import BeautifulSoup, Tag
from ingestion.base import BaseParser, compute_doc_id
from ingestion.models import ExtractedTable, ParsedDocument, SectionNode


class HTMLParser(BaseParser):
    """
    Parses HTML documents (e.g. SEC EDGAR 10-K filings).
    Maintains clean text offsets and structured tables.
    """

    HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def parse_bytes(self, content: bytes, doc_path: str) -> ParsedDocument:
        doc_id = compute_doc_id(content)
        raw_html = content.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")

        soup = BeautifulSoup(raw_html, "html.parser")

        # Remove scripts, styles
        for tag in soup(["script", "style", "meta", "noscript"]):
            tag.decompose()

        body = soup.body or soup

        full_text_parts: list[str] = []
        sections: list[SectionNode] = []
        tables: list[ExtractedTable] = []
        current_offset = 0

        # Iterate over child elements
        for elem in body.descendants:
            if not isinstance(elem, Tag):
                continue

            # Process top-level headings
            if elem.name in self.HEADING_TAGS and elem.parent.name not in self.HEADING_TAGS:
                title = elem.get_text(separator=" ", strip=True)
                if title:
                    header_text = f"\n\n{title}\n\n"
                    start = current_offset
                    full_text_parts.append(header_text)
                    current_offset += len(header_text)
                    level = int(elem.name[1])
                    sections.append(
                        SectionNode(
                            title=title,
                            level=level,
                            char_start=start,
                            char_end=start + len(header_text),
                            page=1,
                        )
                    )

            # Process tables
            elif elem.name == "table" and elem.parent.name != "table":
                # Extract structured table
                headers, rows, caption = self._extract_table_data(elem)
                ext_table_obj = ExtractedTable(
                    headers=headers,
                    rows=rows,
                    char_start=current_offset,
                    char_end=current_offset,  # updated below
                    page=1,
                    section=sections[-1].title if sections else None,
                    caption=caption,
                )
                md_repr = "\n\n" + ext_table_obj.to_markdown() + "\n\n"
                start = current_offset
                full_text_parts.append(md_repr)
                current_offset += len(md_repr)
                end = current_offset

                # update offsets and raw_text
                tables.append(
                    ExtractedTable(
                        headers=headers,
                        rows=rows,
                        char_start=start,
                        char_end=end,
                        page=1,
                        section=sections[-1].title if sections else None,
                        caption=caption,
                        raw_text=md_repr.strip(),
                    )
                )

            # Process paragraphs and blocks
            elif elem.name in {"p", "div", "li"} and not elem.find_parents(["table"]):
                # Avoid processing parent container if already processed
                direct_text = elem.get_text(separator=" ", strip=True)
                if direct_text and elem.find(["p", "div", "table"]) is None:
                    p_text = f"{direct_text}\n\n"
                    full_text_parts.append(p_text)
                    current_offset += len(p_text)

        full_text = "".join(full_text_parts).strip()
        if not full_text:
            # Fallback for plain HTML without standard tags
            full_text = soup.get_text(separator="\n", strip=True)

        # Fix section char_end to extend to next section or end of text
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

    def _extract_table_data(self, table_elem: Tag) -> tuple[list[str], list[list[str]], str | None]:
        headers: list[str] = []
        rows: list[list[str]] = []
        caption_elem = table_elem.find("caption")
        caption = caption_elem.get_text(strip=True) if caption_elem else None

        for tr in table_elem.find_all("tr"):
            th_cells = tr.find_all("th")
            td_cells = tr.find_all("td")
            if th_cells and not headers:
                headers = [c.get_text(separator=" ", strip=True) for c in th_cells]
            elif td_cells:
                rows.append([c.get_text(separator=" ", strip=True) for c in td_cells])

        return headers, rows, caption
