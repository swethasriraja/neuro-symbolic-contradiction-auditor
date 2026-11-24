"""
FAISS vector index over document claims and chunks.
"""
from __future__ import annotations

import logging
from typing import Sequence
import faiss
import numpy as np

from retrieval.embedder import LocalEmbedder
from schemas.claim import Claim

logger = logging.getLogger(__name__)


class FAISSClaimIndex:
    """
    FAISS IndexFlatIP (inner product over normalized vectors = cosine similarity).
    Maps vector indices back to Claim models with reproducible, stable ordering.
    """

    def __init__(self, embedder: Optional[LocalEmbedder] = None):
        self.embedder = embedder or LocalEmbedder()
        self.claims: list[Claim] = []
        self.index: Optional[faiss.IndexFlatIP] = None

    def build_index(self, claims: Sequence[Claim]) -> None:
        """Build FAISS index over claims with stable ordering."""
        # Sort claims by claim_id for determinism
        self.claims = sorted(list(claims), key=lambda c: c.claim_id)
        if not self.claims:
            self.index = faiss.IndexFlatIP(384)
            return

        texts = [f"{c.predicate} {c.raw_text}" for c in self.claims]
        embeddings = self.embedder.encode(texts)

        # Build index
        dim = embeddings.shape[1]
        self.index = faiss.IndexFlatIP(dim)
        self.index.add(embeddings)
        logger.info(f"[FAISSClaimIndex] Built index with {len(self.claims)} claims (dim={dim}).")

    def query_nearest(
        self,
        query_claim: Claim,
        top_k: int = 5,
        threshold: float = 0.80,
    ) -> list[tuple[Claim, float]]:
        """
        Query FAISS index for nearest neighbor claims.
        Returns list of (claim, cosine_similarity) tuples above threshold.
        """
        if self.index is None or len(self.claims) == 0:
            return []

        query_text = f"{query_claim.predicate} {query_claim.raw_text}"
        query_vec = self.embedder.encode([query_text])

        k = min(top_k + 1, len(self.claims))  # +1 because claim might match itself
        distances, indices = self.index.search(query_vec, k)

        results: list[tuple[Claim, float]] = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0 or idx >= len(self.claims):
                continue
            neighbor = self.claims[idx]
            if neighbor.claim_id == query_claim.claim_id:
                continue  # skip self
            score = float(dist)
            if score >= threshold:
                results.append((neighbor, score))

        return results
