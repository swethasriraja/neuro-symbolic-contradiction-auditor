"""
Pydantic v2 schemas for API requests and responses.
Reuses domain models and exact naming enums:
CONTRADICTION | CONSISTENT | UNRESOLVED and SAT | UNSAT | UNKNOWN.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class DocumentUploadResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    doc_id: str
    filename: str
    file_format: str
    char_length: int
    created_at: datetime


class AuditCreateRequest(BaseModel):
    doc_ids: list[str] = Field(min_length=1)
    module: str = Field(pattern="^(legal|financial)$")
    system: str = Field(default="full", pattern="^(full|no_debate)$")
    config_overrides: dict[str, Any] = Field(default_factory=dict)


class AuditCreateResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    audit_id: str
    status: str = "queued"
    created_at: datetime


class AuditStatusResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    audit_id: str
    doc_id: str
    module: str
    system_type: str
    status: str
    progress: float
    pairs_total: int
    pairs_completed: int
    total_tokens: int
    total_cost_usd: float
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class FindingSummaryResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    finding_id: str
    pair_id: str
    status: str
    severity: str
    confidence: float
    title: str
    spans_verified: bool
    judge_overruled: bool


class FindingDetailResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    finding_id: str
    audit_id: str
    pair_id: str
    status: str
    severity: str
    confidence: float
    title: str
    description: str
    claim_a_text: str
    claim_a_start: int
    claim_a_end: int
    claim_b_text: str
    claim_b_start: int
    claim_b_end: int
    spans_verified: bool
    judge_overruled: bool
    overrule_reason: Optional[str] = None
    unresolved_reason: Optional[str] = None
    solver_outcome: Optional[str] = None
    solver_backend: Optional[str] = None
    solver_proof_trace: Optional[str] = None
    unsat_core: Optional[list] = None


class ExactTextResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    doc_id: str
    start: int
    end: int
    text: str


class DebateTranscriptMessageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    message_id: str
    round_number: int
    sender: str
    argument_text: str
    cited_claim_ids: list
    cost_usd: float


class DebateTranscriptResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    thread_id: str
    pair_id: str
    rounds_used: int
    status: str
    final_verdict: Optional[str]
    messages: list[DebateTranscriptMessageResponse]


class HumanReviewRequest(BaseModel):
    decision: str = Field(pattern="^(confirm|dismiss|needs_more_info)$")
    notes: Optional[str] = None


class HumanReviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    review_id: str
    finding_id: str
    decision: str
    notes: Optional[str]
    reviewed_at: datetime
    message: str = "Review recorded successfully. System verdict remains unchanged."
