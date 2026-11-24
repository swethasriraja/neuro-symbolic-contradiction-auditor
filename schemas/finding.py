"""
Finding — the terminal auditor output for one CandidatePair.

A Finding is the record that a human reviewer or downstream system sees.
It wraps a SolverResult with human-readable context, evidence provenance,
severity, and review flags.

Invariants (enforced at parse time)
-------------------------------------
1. CONTRADICTION requires spans_verified=True AND solver_outcome=UNSAT.
   Both conditions must hold; either alone is insufficient.

2. UNRESOLVED requires unresolved_reason to be non-null.
   A flag without a reason is an audit gap.

3. UNRESOLVED findings are capped at Severity.MEDIUM.
   Only CONTRADICTION findings may carry CRITICAL or HIGH severity,
   because uncertain findings should not trigger high-stakes responses.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.solver import SolverOutcome
from schemas.span import SourceSpan


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FindingStatus(str, Enum):
    CONTRADICTION = "contradiction"
    CONSISTENT = "consistent"
    UNRESOLVED = "unresolved"


_UNRESOLVED_ALLOWED_SEVERITIES: frozenset[Severity] = frozenset(
    {Severity.MEDIUM, Severity.LOW, Severity.INFO}
)


class Finding(BaseModel):
    """Final auditor output for a single CandidatePair analysis."""

    model_config = ConfigDict(frozen=True)

    finding_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Stable UUID4."""

    pair_id: str
    """Foreign-key reference to the CandidatePair that was analysed."""

    solver_result_id: str
    """Foreign-key reference to the SolverResult that determined the verdict."""

    solver_outcome: SolverOutcome
    """Denormalised copy of SolverResult.outcome: UNSAT | SAT | UNKNOWN."""

    status: FindingStatus
    """Verdict: CONTRADICTION | CONSISTENT | UNRESOLVED."""

    severity: Severity
    """Risk level. UNRESOLVED findings are capped at MEDIUM."""

    confidence: float = Field(ge=0.0, le=1.0)
    """Composite confidence in this finding (extractor × solver × verification)."""

    title: str
    """Short human-readable summary, e.g. 'Payment term contradiction (§4.2 vs §8.1)'."""

    description: str
    """Full explanation of the contradiction or finding."""

    claim_a_span: SourceSpan
    """SourceSpan copied from claim_a. Must be verified against source text."""

    claim_b_span: SourceSpan
    """SourceSpan copied from claim_b. Must be verified against source text."""

    spans_verified: bool
    """True only if both claim spans were confirmed to exist in the source document."""

    unresolved_flag: bool = False
    """True → this finding requires human review before any action is taken."""

    unresolved_reason: Optional[str] = None
    """Why the finding could not be automatically resolved.
    Required when unresolved_flag=True."""

    debate_thread_id: Optional[str] = None
    """Foreign-key reference to the DebateThread, if debate was run."""

    judge_overruled: bool = False
    """True if code enforcement gate overruled the Judge's proposed verdict."""

    judge_overrule_reason: Optional[str] = None
    """Explanation of why the Judge's verdict was overruled by code constraints."""

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    reviewed_by: Optional[str] = None
    """Human reviewer identifier (populated post-review)."""

    reviewed_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _validate_invariants(self) -> "Finding":
        # Invariant 1a: CONTRADICTION requires verified spans
        if (
            self.status == FindingStatus.CONTRADICTION
            and not self.spans_verified
        ):
            raise ValueError(
                "Finding.status=CONTRADICTION requires spans_verified=True; "
                "a confirmed contradiction must have verifiable source evidence"
            )

        # Invariant 1b: CONTRADICTION requires UNSAT solver outcome
        if (
            self.status == FindingStatus.CONTRADICTION
            and self.solver_outcome != SolverOutcome.UNSAT
        ):
            raise ValueError(
                f"Finding.status=CONTRADICTION requires solver_outcome=UNSAT, "
                f"got solver_outcome={self.solver_outcome.value!r}; "
                "the solver must prove the contradiction"
            )

        # Invariant 2: UNRESOLVED requires a reason
        if self.unresolved_flag and self.unresolved_reason is None:
            raise ValueError(
                "unresolved_flag=True requires unresolved_reason to be set; "
                "an unresolved finding without a reason is an audit gap"
            )

        # Invariant 3: UNRESOLVED severity cap at MEDIUM
        if (
            self.status == FindingStatus.UNRESOLVED
            and self.severity not in _UNRESOLVED_ALLOWED_SEVERITIES
        ):
            raise ValueError(
                f"UNRESOLVED findings may not have severity={self.severity.value!r}; "
                f"maximum allowed severity is MEDIUM "
                f"(only CONTRADICTION findings may carry CRITICAL or HIGH)"
            )

        return self
