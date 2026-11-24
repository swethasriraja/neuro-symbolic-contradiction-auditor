"""
Base parser interface for all document formats.
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Union

from ingestion.models import ParsedDocument


def compute_doc_id(data: bytes) -> str:
    """Compute SHA-256 hex digest for document bytes."""
    return hashlib.sha256(data).hexdigest()


class BaseParser(ABC):
    """Abstract parser interface converting input documents into ParsedDocument."""

    @abstractmethod
    def parse_bytes(self, content: bytes, doc_path: str) -> ParsedDocument:
        """Parse raw document bytes into a ParsedDocument."""
        pass

    def parse_file(self, file_path: Union[str, Path]) -> ParsedDocument:
        """Read file from disk and parse."""
        path = Path(file_path)
        content = path.read_bytes()
        return self.parse_bytes(content, str(path))
