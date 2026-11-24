"""
Embedding generator using local Hugging Face sentence-transformers.
Runs completely offline with fixed seed and deterministic normalization.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional, Sequence
import numpy as np

logger = logging.getLogger(__name__)


class LocalEmbedder:
    """Generates local dense embeddings using sentence-transformers or a deterministic mock."""

    def __init__(
        self,
        model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        use_mock: bool = False,
    ):
        self.model_name = model_name
        self.use_mock = use_mock
        self._model = None

    def _get_model(self):
        if self._model is None and not self.use_mock:
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name)
            except Exception as e:
                logger.warning(
                    f"Could not load SentenceTransformer '{self.model_name}': {e}. "
                    "Falling back to deterministic pseudo-embeddings."
                )
                self.use_mock = True
        return self._model

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """
        Encode a sequence of texts into normalized float32 embeddings (dim=384).
        """
        if not texts:
            return np.empty((0, 384), dtype=np.float32)

        if not self.use_mock:
            try:
                model = self._get_model()
                if model is not None:
                    vectors = model.encode(
                        list(texts),
                        convert_to_numpy=True,
                        normalize_embeddings=True,
                        show_progress_bar=False,
                    )
                    return vectors.astype(np.float32)
            except Exception as e:
                logger.warning(f"Embedding execution error: {e}. Using deterministic fallback.")

        # Deterministic offline mock embedding based on SHA-256 tokens
        embeddings = []
        for text in texts:
            vec = np.zeros(384, dtype=np.float32)
            for word in text.lower().split():
                h = int(hashlib.sha256(word.encode("utf-8")).hexdigest(), 16)
                idx = h % 384
                vec[idx] += 1.0
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            else:
                vec[0] = 1.0
            embeddings.append(vec)

        return np.array(embeddings, dtype=np.float32)
