"""
ingestion package — document parsers and chunkers.
"""

from ingestion.base import BaseParser, compute_doc_id
from ingestion.chunker import SectionAwareChunker
from ingestion.docx import DocxParser
from ingestion.html import HTMLParser
from ingestion.models import (
    ExtractedTable,
    NonExtractableDocumentError,
    ParsedDocument,
    SectionNode,
)
from ingestion.pdf import PDFParser
from ingestion.txt import PlainTextParser

__all__ = [
    "BaseParser",
    "compute_doc_id",
    "SectionAwareChunker",
    "DocxParser",
    "HTMLParser",
    "ExtractedTable",
    "NonExtractableDocumentError",
    "ParsedDocument",
    "SectionNode",
    "PDFParser",
    "PlainTextParser",
]
