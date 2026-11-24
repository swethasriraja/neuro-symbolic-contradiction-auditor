"""
Claim schemas: LegalClaim, FinancialClaim, Claim (union), ClaimModule, ClaimSet.

Design decisions
----------------
1. `module` literal field — discriminates the Claim union without ambiguity.
   LegalClaimType and FinancialMetric are intentionally disjoint enum sets,
   but we use an explicit Literal discriminator rather than relying on that
   property, which is fragile to enum expansion.

2. `defined_terms` on LegalClaim — defined-term mismatch ("Business Day" vs
   "day") is the #1 source of legal false positives. Embedding the resolved
   definition at claim-creation time means the solver sees the same meaning
   the extractor did, regardless of how the term is used elsewhere.

3. `scope_qualifier` on LegalClaim — many apparent contradictions are scoped:
   "payment due in 30 days" vs "payment due in 15 days *for late deliveries*".
   Capturing the qualifier lets the solver rule these out as conditional, not
   contradictory.

4. `Decimal` for FinancialClaim.value — financial figures require exact
   representation. float(1_234_567.89) accumulates rounding error that could
   produce phantom contradictions. Decimal stores values exactly as written.

5. `entity` on FinancialClaim — annual reports contain consolidated *and*
   subsidiary figures. Without entity tagging, parent vs. subsidiary revenue
   figures look like contradictions but are not.

6. ClaimSet uses `list[Claim]` (discriminated union) so Pydantic deserialises
   each element via the `module` discriminator, then the model_validator checks
   that every claim's module matches the set's declared module.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.span import SourceSpan


# ── Legal ──────────────────────────────────────────────────────────────────

class LegalClaimType(str, Enum):
    OBLIGATION = "obligation"
    RIGHT = "right"
    PROHIBITION = "prohibition"
    CONDITION = "condition"
    DEADLINE = "deadline"
    PARTY = "party"
    AMOUNT = "amount"
    TERMINATION_TRIGGER = "termination_trigger"
    DEFINED_TERM = "defined_term"


class LegalClaim(BaseModel):
    """An extracted claim from a legal contract."""

    model_config = ConfigDict(frozen=True)

    module: Literal["legal"] = "legal"
    """Discriminator for the Claim union. Always 'legal'. Do not override."""

    claim_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Stable UUID4. Set once at extraction; NEVER mutated downstream."""

    claim_type: LegalClaimType
    """Semantic type of this legal claim."""

    predicate: str
    """Normalised logical form used by the solver.
    E.g. 'payment_due(Party.Licensee, 30, days)'."""

    raw_text: str
    """Verbatim sentence(s) from which this claim was extracted."""

    span: SourceSpan
    """Precise source location. Missing span → ValidationError at parse time."""

    parties: list[str] = Field(default_factory=list)
    """Named contract parties involved, e.g. ['Licensee', 'Licensor']."""

    defined_terms: dict[str, str] = Field(default_factory=dict)
    """Resolved definitions for terms used in this claim.
    E.g. {'Business Day': 'Mon–Fri excluding public holidays'}.
    Embedding at claim-creation time prevents defined-term false positives."""

    scope_qualifier: Optional[str] = None
    """Conditional qualifier that scopes this claim.
    E.g. 'unless written notice is given 30 days prior'.
    Prevents phantom contradictions from conditional clauses."""

    confidence: float = Field(ge=0.0, le=1.0)
    """Extractor confidence score, 0.0–1.0."""

    extractor: str
    """Identity of the extractor.
    E.g. 'llm:claude-3-5-sonnet-20241022' or 'rule:regex_payment_v1'."""

    extracted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ── Financial ──────────────────────────────────────────────────────────────

class FinancialMetric(str, Enum):
    REVENUE = "revenue"
    EXPENSE = "expense"
    NET_INCOME = "net_income"
    GROSS_PROFIT = "gross_profit"
    EBITDA = "ebitda"
    EPS = "eps"
    TOTAL_ASSETS = "total_assets"
    TOTAL_LIABILITIES = "total_liabilities"
    EQUITY = "equity"
    CASH_FLOW = "cash_flow"
    RATIO = "ratio"
    PERCENTAGE = "percentage"
    DATE = "date"
    PERIOD = "period"
    OTHER = "other"


class SourceType(str, Enum):
    """Where in the financial document this claim originates."""
    NARRATIVE = "narrative"
    TABLE = "table"
    FOOTNOTE = "footnote"


class FinancialClaim(BaseModel):
    """An extracted claim from a financial document (annual report / SEC filing)."""

    model_config = ConfigDict(frozen=True)

    module: Literal["financial"] = "financial"
    """Discriminator for the Claim union. Always 'financial'. Do not override."""

    claim_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Stable UUID4. Set once at extraction; NEVER mutated downstream."""

    metric: FinancialMetric
    """The financial metric this claim asserts a value for."""

    value: Optional[Decimal] = None
    """Exact numeric value as Decimal (never float).
    Decimal preserves the precision written in the source document and
    avoids rounding-artifact phantom contradictions."""

    unit: Optional[str] = None
    """Unit of measurement, e.g. 'USD', 'GBP millions', 'shares', '%'."""

    period: Optional[str] = None
    """ISO 8601 date or interval.
    E.g. '2023-01-01/2023-12-31', '2023', 'Q3-2023'."""

    entity: Optional[str] = None
    """Reporting entity or subsidiary name.
    E.g. 'Apple Inc.', 'EMEA Segment'.
    Required to prevent parent-vs-subsidiary false positives."""

    source_type: SourceType
    """Whether this claim came from narrative prose, a data table, or a footnote."""

    predicate: str
    """Normalised logical form used by the solver.
    E.g. 'revenue(Apple_Inc, FY2023, 383285000000, USD)'."""

    raw_text: str
    """Verbatim sentence or table cell content from the source document."""

    span: SourceSpan
    """Precise source location. Missing span → ValidationError at parse time."""

    confidence: float = Field(ge=0.0, le=1.0)
    """Extractor confidence score, 0.0–1.0."""

    extractor: str
    """Identity of the extractor."""

    extracted_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ── Union and ClaimSet ─────────────────────────────────────────────────────

Claim = Annotated[
    Union[LegalClaim, FinancialClaim],
    Field(discriminator="module"),
]
"""Discriminated union of legal and financial claims.
Use the 'module' field ('legal' | 'financial') to dispatch.
Both branches share: claim_id, span, confidence, extractor, extracted_at."""


class ClaimModule(str, Enum):
    LEGAL = "legal"
    FINANCIAL = "financial"


class ClaimSet(BaseModel):
    """
    All claims extracted from a single document, grouped by module.

    ClaimSet is the typed input unit for the retrieval and solver layers.
    One document produces one ClaimSet per module (legal XOR financial).
    Cross-document ClaimSets are v2; not supported here.

    Invariant: every claim in `claims` must have claim.module == self.module.
    """

    model_config = ConfigDict(frozen=False)
    # Mutable so Step 2 extraction can append claims incrementally.

    set_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    doc_id: str
    doc_path: str
    module: ClaimModule
    claims: list[Claim] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_claims_match_module(self) -> "ClaimSet":
        expected_module = self.module.value  # "legal" or "financial"
        for i, claim in enumerate(self.claims):
            if claim.module != expected_module:
                raise ValueError(
                    f"ClaimSet module={self.module.value.upper()} but "
                    f"claims[{i}] has module='{claim.module}' "
                    f"(claim_id={claim.claim_id!r})"
                )
        return self
