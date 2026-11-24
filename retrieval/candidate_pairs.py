"""
Hybrid Candidate Pair Generator (FAISS + Deterministic Rules).

Combines:
1. FAISS embedding cosine similarity (top-k, threshold).
2. Step 3 deterministic rule pairs (same party/action, same metric/period).
3. Enforces max_candidate_pairs cap strictly for pairs sent to debate.
4. Breaks ties deterministically: (-similarity_score, claim_a.claim_id, claim_b.claim_id).
5. Logs per document how many candidate pairs were dropped by the cap.
"""
from __future__ import annotations

import logging
from typing import Optional, Sequence

from retrieval.faiss_index import FAISSClaimIndex
from schemas.claim import Claim
from schemas.pair import CandidatePair
from symbolic.candidate_pairs import CandidatePairGenerator

logger = logging.getLogger(__name__)


class HybridCandidatePairGenerator:
    """Generates candidate contradiction pairs using FAISS retrieval and deterministic rules."""

    def __init__(
        self,
        faiss_index: Optional[FAISSClaimIndex] = None,
        top_k: int = 5,
        similarity_threshold: float = 0.80,
        max_candidate_pairs: int = 25,
    ):
        self.faiss_index = faiss_index or FAISSClaimIndex()
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold
        self.max_candidate_pairs = max_candidate_pairs

    def generate_candidate_pairs(
        self,
        claims: Sequence[Claim],
        apply_cap_for_debate: bool = True,
    ) -> list[CandidatePair]:
        """
        Generate hybrid candidate pairs from a document's claims.

        Args:
            claims: All extracted claims from the document.
            apply_cap_for_debate: If True, applies max_candidate_pairs cap.
                                 If False, returns all generated candidate pairs.

        Returns:
            Deduplicated, deterministically ordered list of CandidatePairs.
        """
        if len(claims) < 2:
            return []

        doc_id = claims[0].span.doc_id

        # 1. Deterministic Rule Pairs (from Step 3)
        rule_pairs = CandidatePairGenerator.generate_pairs(claims)

        # 2. Embedding Retrieval Pairs via FAISS
        self.faiss_index.build_index(claims)
        embedding_pairs_dict: dict[tuple[str, str], tuple[Claim, Claim, float]] = {}

        for claim in claims:
            neighbors = self.faiss_index.query_nearest(
                query_claim=claim,
                top_k=self.top_k,
                threshold=self.similarity_threshold,
            )
            for neighbor, score in neighbors:
                # Canonical pair key (sorted by claim_id)
                key = (
                    min(claim.claim_id, neighbor.claim_id),
                    max(claim.claim_id, neighbor.claim_id),
                )
                if key not in embedding_pairs_dict or score > embedding_pairs_dict[key][2]:
                    # Keep claim ordering matching key
                    c_a = claim if claim.claim_id == key[0] else neighbor
                    c_b = neighbor if neighbor.claim_id == key[1] else claim
                    embedding_pairs_dict[key] = (c_a, c_b, score)

        # 3. Union & Merge
        merged_pairs: dict[tuple[str, str], CandidatePair] = {}

        # Add deterministic pairs first
        for p in rule_pairs:
            key = (
                min(p.claim_a.claim_id, p.claim_b.claim_id),
                max(p.claim_a.claim_id, p.claim_b.claim_id),
            )
            merged_pairs[key] = p

        # Add / upgrade embedding pairs
        for key, (c_a, c_b, score) in embedding_pairs_dict.items():
            if key in merged_pairs:
                # Retain existing, update metadata
                merged_pairs[key] = merged_pairs[key].model_copy(
                    update={
                        "similarity_score": max(merged_pairs[key].similarity_score, score),
                        "retrieval_method": "hybrid_rule_and_faiss",
                    }
                )
            else:
                merged_pairs[key] = CandidatePair(
                    claim_a=c_a,
                    claim_b=c_b,
                    similarity_score=score,
                    retrieval_method="faiss_cosine",
                    metadata={"module": c_a.module},
                )

        candidate_list = list(merged_pairs.values())
        total_generated = len(candidate_list)

        # 4. Deterministic Sort: (-similarity_score, claim_a.claim_id, claim_b.claim_id)
        candidate_list.sort(
            key=lambda p: (-p.similarity_score, p.claim_a.claim_id, p.claim_b.claim_id)
        )

        # 5. Cap Enforcement for Debate
        if apply_cap_for_debate and total_generated > self.max_candidate_pairs:
            dropped_count = total_generated - self.max_candidate_pairs
            candidate_list = candidate_list[: self.max_candidate_pairs]
            logger.info(
                f"[HybridCandidatePairGenerator] Doc {doc_id[:8]}...: "
                f"Generated {total_generated} pairs, capped at {self.max_candidate_pairs}. "
                f"DROPPED {dropped_count} candidate pairs due to max_candidate_pairs cap."
            )
        else:
            logger.info(
                f"[HybridCandidatePairGenerator] Doc {doc_id[:8]}...: "
                f"Selected all {total_generated} candidate pairs for debate (below cap {self.max_candidate_pairs})."
            )

        return candidate_list
