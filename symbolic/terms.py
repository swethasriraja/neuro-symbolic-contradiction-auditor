"""
Defined-term and scope resolution.

NON-NEGOTIABLE PRINCIPLE:
Defined-term and scope resolution must be applied BEFORE any candidate pair is compared.
- If two claims use the same term with different definitions, the result is UNRESOLVED.
- If a term has no definition, or units differ (e.g. "Business Day" vs "day"),
  they must NOT be conflated as a false-positive contradiction.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from schemas.claim import Claim, LegalClaim, FinancialClaim


class ScopeStatus(str, Enum):
    COMPATIBLE = "compatible"
    MISMATCHED_UNITS = "mismatched_units"
    CONFLICTING_DEFINITIONS = "conflicting_definitions"
    CONDITIONAL_EXCEPTION = "conditional_exception"
    AMBIGUOUS_SCOPE = "ambiguous_scope"


@dataclass(frozen=True)
class TermResolution:
    status: ScopeStatus
    reason: Optional[str] = None
    should_audit: bool = True
    unresolved_reason: Optional[str] = None


class TermResolver:
    """Pre-solver gate checking defined terms, units, and scope qualifiers."""

    @classmethod
    def resolve_pair_scope(cls, claim_a: Claim, claim_b: Claim) -> TermResolution:
        """
        Analyze defined terms and scope qualifiers between two candidate claims.
        Returns TermResolution indicating whether the pair can proceed to the solver.
        """
        # 1. Legal defined terms check
        if isinstance(claim_a, LegalClaim) and isinstance(claim_b, LegalClaim):
            # Check for "Business Day" vs "day" disparity in predicates or raw text
            text_a = f"{claim_a.raw_text} {claim_a.predicate}".lower()
            text_b = f"{claim_b.raw_text} {claim_b.predicate}".lower()

            has_bday_a = "business day" in text_a or "bday" in text_a
            has_bday_b = "business day" in text_b or "bday" in text_b
            has_cday_a = (" day" in text_a or " days" in text_a) and not has_bday_a
            has_cday_b = (" day" in text_b or " days" in text_b) and not has_bday_b

            if (has_bday_a and has_cday_b) or (has_cday_a and has_bday_b):
                # Check if document explicitly defined "Business Day" as calendar day
                defs = {**claim_a.defined_terms, **claim_b.defined_terms}
                bday_def = defs.get("Business Day", "").lower()
                if "calendar" not in bday_def and "every day" not in bday_def:
                    return TermResolution(
                        status=ScopeStatus.MISMATCHED_UNITS,
                        reason="Disparity between Business Days and Calendar Days without equivalence definition.",
                        should_audit=False,
                        unresolved_reason="Disparity between Business Days and Calendar Days; not directly contradictory.",
                    )

            # Check for conflicting defined terms
            common_terms = set(claim_a.defined_terms.keys()) & set(claim_b.defined_terms.keys())
            for term in common_terms:
                def_a = claim_a.defined_terms[term].strip().lower()
                def_b = claim_b.defined_terms[term].strip().lower()
                if def_a != def_b and def_a not in def_b and def_b not in def_a:
                    return TermResolution(
                        status=ScopeStatus.CONFLICTING_DEFINITIONS,
                        reason=f"Defined term '{term}' has conflicting definitions between clauses: '{def_a}' vs '{def_b}'",
                        should_audit=False,
                        unresolved_reason=f"Ambiguous/conflicting definitions for term '{term}'. Flagged for human review.",
                    )

            # Check for conditional scope qualifiers ("unless", "except as provided in")
            qual_a = (claim_a.scope_qualifier or "").strip().lower()
            qual_b = (claim_b.scope_qualifier or "").strip().lower()
            if qual_a or qual_b:
                if any(k in qual_a or k in qual_b for k in ["unless", "except", "subject to", "provided that", "in the event"]):
                    return TermResolution(
                        status=ScopeStatus.CONDITIONAL_EXCEPTION,
                        reason=f"One or both clauses are scoped by conditional exceptions ('{qual_a or qual_b}').",
                        should_audit=False,
                        unresolved_reason="Conditional clause/exception overrides absolute contradiction.",
                    )

        # 2. Financial scope check (period and entity alignment)
        elif isinstance(claim_a, FinancialClaim) and isinstance(claim_b, FinancialClaim):
            # Check period mismatch (e.g. FY2023 vs FY2022, or FY2023 vs Q1 2023)
            p_a = (claim_a.period or "").strip().lower()
            p_b = (claim_b.period or "").strip().lower()
            if p_a and p_b and p_a != p_b and not (p_a in p_b or p_b in p_a):
                return TermResolution(
                    status=ScopeStatus.AMBIGUOUS_SCOPE,
                    reason=f"Financial claims reference different reporting periods ('{p_a}' vs '{p_b}').",
                    should_audit=False,
                    unresolved_reason="Different reporting periods cannot be directly compared for contradiction.",
                )

            # Check entity mismatch (allow cross-checking segment sum vs total row)
            e_a = (claim_a.entity or "").strip().lower()
            e_b = (claim_b.entity or "").strip().lower()
            if e_a and e_b and e_a != e_b:
                if not ({"total", "segment sum", "company"} & {e_a, e_b}):
                    return TermResolution(
                        status=ScopeStatus.AMBIGUOUS_SCOPE,
                        reason=f"Financial claims reference different entities ('{e_a}' vs '{e_b}').",
                        should_audit=False,
                        unresolved_reason="Different reporting entities (e.g. segment vs parent) cannot be compared directly.",
                    )

        return TermResolution(status=ScopeStatus.COMPATIBLE, should_audit=True)
