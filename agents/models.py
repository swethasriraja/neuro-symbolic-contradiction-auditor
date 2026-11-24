"""
Pydantic data models for agent messages and verifier evaluations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from schemas.solver import SolverResult


class AuditorArgument(BaseModel):
    """Structured output emitted by the Auditor agent."""
    claim_ids: list[str] = Field(min_length=1)
    contradiction_type: str = "general"
    assertion: str
    reasoning: str
    cited_snippets: list[str] = Field(default_factory=list)


class DefenderArgument(BaseModel):
    """Structured output emitted by the Defender agent."""
    reconciliation_type: str = "none"
    # Options: scope_exception, period_mismatch, entity_mismatch, amendment_override, definition_difference, none
    explanation: str
    cited_claim_ids: list[str] = Field(default_factory=list)
    reconciliation_basis: str = "none"
    supporting_snippet: str = ""


class JudgeVerdict(BaseModel):
    """Structured output emitted by the Judge agent."""
    proposed_status: str  # contradiction | consistent | unresolved
    confidence: float = Field(ge=0.0, le=1.0, default=0.95)
    severity: str = "medium"  # critical | high | medium | low | info
    title: str = "Audit Finding"
    verdict_summary: str


@dataclass(frozen=True)
class VerifierEvaluation:
    """Deterministic evaluation record produced by the Verifier engine."""
    solver_result: SolverResult
    spans_verified: bool
    reconciliation_valid: bool
    reconciliation_reason: Optional[str]
    is_decisive: bool
    unresolved_reason: Optional[str] = None


@dataclass
class DebateBudget:
    """Execution budgets for debate loop."""
    max_rounds: int = 3
    per_pair_token_budget: int = 8000
    per_pair_cost_budget_usd: Decimal = Decimal("0.15")
    per_document_cost_budget_usd: Decimal = Decimal("2.00")
