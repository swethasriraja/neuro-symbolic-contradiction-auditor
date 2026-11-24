"""
Deterministic Candidate Pair Generator.

Generates CandidatePairs within a document by grouping claims on:
- Same party and action/subject (Legal)
- Same metric, entity, and period, or percentage/growth vs base metric (Financial)
- Cross-checking narrative vs tabular claims
NO FAISS or embedding retrieval is used in this step.
"""
from __future__ import annotations

import re
from typing import Sequence

from schemas.claim import Claim, FinancialClaim, FinancialMetric, LegalClaim
from schemas.pair import CandidatePair


def extract_action_keyword(predicate: str, raw_text: str) -> str:
    """Extract primary domain action keyword (e.g. payment, termination, cure, notice, fee)."""
    combined = f"{predicate} {raw_text}".lower()
    for kw in ["payment", "pay", "terminate", "termination", "cure", "notice", "fee", "confidential", "liability", "term"]:
        if kw in combined:
            return kw
    match = re.match(r"^([a-z_]+)", predicate.lower())
    return match.group(1) if match else "general"


class CandidatePairGenerator:
    """Generates candidate contradiction pairs deterministically."""

    @classmethod
    def generate_pairs(cls, claims: Sequence[Claim]) -> list[CandidatePair]:
        """Generate candidate pairs from a collection of claims from the same document."""
        pairs: list[CandidatePair] = []
        n = len(claims)
        if n < 2:
            return pairs

        for i in range(n):
            for j in range(i + 1, n):
                claim_a = claims[i]
                claim_b = claims[j]

                # Must be same document
                if claim_a.span.doc_id != claim_b.span.doc_id:
                    continue

                if cls._should_pair(claim_a, claim_b):
                    pairs.append(
                        CandidatePair(
                            claim_a=claim_a,
                            claim_b=claim_b,
                            similarity_score=1.0,
                            retrieval_method="deterministic_rule_v1",
                            metadata={"module": claim_a.module},
                        )
                    )

        return pairs

    @classmethod
    def _should_pair(cls, a: Claim, b: Claim) -> bool:
        """Evaluate if two claims have overlapping topics that warrant solver verification."""
        # 1. Legal pairing
        if isinstance(a, LegalClaim) and isinstance(b, LegalClaim):
            parties_a = set(p.lower() for p in a.parties)
            parties_b = set(p.lower() for p in b.parties)
            common_parties = bool(parties_a & parties_b) or (not parties_a and not parties_b)

            if not common_parties:
                return False

            action_a = extract_action_keyword(a.predicate, a.raw_text)
            action_b = extract_action_keyword(b.predicate, b.raw_text)

            if action_a == action_b and action_a != "general":
                return True

            if a.claim_type == b.claim_type:
                return True

            from schemas.claim import LegalClaimType
            if {a.claim_type, b.claim_type} in [{LegalClaimType.OBLIGATION, LegalClaimType.PROHIBITION},
                                                {LegalClaimType.RIGHT, LegalClaimType.PROHIBITION}]:
                return action_a == action_b

            return False

        # 2. Financial pairing
        elif isinstance(a, FinancialClaim) and isinstance(b, FinancialClaim):
            # Same metric, or percentage/ratio with matching financial subject
            if a.metric == b.metric:
                metrics_match = True
            elif {a.metric, b.metric} & {FinancialMetric.PERCENTAGE, FinancialMetric.RATIO}:
                subj_a = set(re.findall(r"\b(revenue|debt|ebitda|profit|income|margin|expense|asset|liability|dividend)\b", (a.raw_text + " " + (a.predicate or "")).lower()))
                subj_b = set(re.findall(r"\b(revenue|debt|ebitda|profit|income|margin|expense|asset|liability|dividend)\b", (b.raw_text + " " + (b.predicate or "")).lower()))
                metrics_match = bool(subj_a & subj_b) or not subj_a or not subj_b
            else:
                metrics_match = False

            if not metrics_match:
                return False

            e_a = (a.entity or "").strip().lower()
            e_b = (b.entity or "").strip().lower()
            if e_a and e_b and e_a != e_b:
                # Allow cross-checking segment sum vs total or company totals
                if not ({"total", "segment sum", "company"} & {e_a, e_b}):
                    return False

            p_a = (a.period or "").strip().lower()
            p_b = (b.period or "").strip().lower()
            if p_a and p_b and p_a != p_b:
                if not (p_a in p_b or p_b in p_a):
                    return False

            return True

        return False
