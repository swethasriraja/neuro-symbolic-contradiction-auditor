"""
retrieval package — FAISS vector index, embeddings, and hybrid candidate pair generator.
"""

from retrieval.candidate_pairs import HybridCandidatePairGenerator
from retrieval.embedder import LocalEmbedder
from retrieval.faiss_index import FAISSClaimIndex

__all__ = [
    "LocalEmbedder",
    "FAISSClaimIndex",
    "HybridCandidatePairGenerator",
]
