"""
Data models for the evaluation harness and contradiction injection.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field

from schemas.finding import Finding, FindingStatus
from schemas.span import SourceSpan


class InjectionCategory(str, Enum):
    LEGAL = "legal"
    FINANCIAL = "financial"
    HARD_NEGATIVE = "hard_negative"
    CLEAN = "clean"


class InjectionType(str, Enum):
    # Legal injections
    DEADLINE_ALTERATION = "deadline_alteration"
    CURE_PERIOD_CONFLICT = "cure_period_conflict"
    OBLIGATION_TO_PROHIBITION = "obligation_to_prohibition"
    PAYMENT_DUE_DATE = "payment_due_date"
    PAYMENT_AMOUNT_MISMATCH = "payment_amount_mismatch"
    GOVERNING_LAW_CONFLICT = "governing_law_conflict"
    DEFINED_TERM_MUTATION = "defined_term_mutation"

    # Financial injections
    GROWTH_RATE_DISPARITY = "growth_rate_disparity"
    TABLE_SUM_CORRUPTION = "table_sum_corruption"
    UNIT_SCALE_SWAP = "unit_scale_swap"
    SIGN_FLIP = "sign_flip"
    PERIOD_LABEL_MUTATION = "period_label_mutation"

    # Hard Negatives (Must NOT be flagged as CONTRADICTION)
    ROUNDING_WITHIN_TOLERANCE = "rounding_within_tolerance"
    DIFFERENT_REPORTING_PERIODS = "different_reporting_periods"
    DIFFERENT_ENTITY_SCOPES = "different_entity_scopes"
    AMENDMENT_OVERRIDE_CLAUSE = "amendment_override_clause"
    BUSINESS_VS_CALENDAR_DAYS = "business_vs_calendar_days"
    CONDITIONAL_SCOPE_EXCEPTION = "conditional_scope_exception"

    # Clean
    NONE = "none"


class GroundTruthAnnotation(BaseModel):
    """
    Ground-truth manifest accompanying an injected (or clean) document.
    """
    model_config = ConfigDict(frozen=True)

    injection_id: str
    doc_id: str
    category: InjectionCategory
    injection_type: InjectionType
    expected_verdict: FindingStatus
    original_span_a: SourceSpan
    original_span_b: SourceSpan
    modified_span: Optional[SourceSpan] = None
    mutation_description: str
    seed: int
    expected_unsat_core: Optional[list[str]] = None


class InjectedDocument(BaseModel):
    """Container for an injected document and its ground-truth annotations."""
    model_config = ConfigDict(frozen=True)

    doc_id: str
    title: str
    full_text: str
    annotations: list[GroundTruthAnnotation]
    tables: list[dict[str, Any]] = Field(default_factory=list)


class EvalSystemOutput(BaseModel):
    """Standardized output container for any evaluation system."""
    model_config = ConfigDict(frozen=True)

    system_id: str
    doc_id: str
    findings: list[Finding]
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    latency_seconds: float = 0.0
    llm_calls_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
