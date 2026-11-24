"""
SolverResult — symbolic solver output.

Produced by the Z3 or Datalog backend. Never fabricated.

Validation rules (enforced at parse time)
------------------------------------------
- If outcome == UNSAT, proof_trace must be non-null.
  A contradiction verdict without a checkable proof trace is invalid.
- UNKNOWN may have null proof_trace (expected on timeout or unhandled logic).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SolverBackend(str, Enum):
    Z3 = "z3"
    DATALOG = "datalog"


class SolverOutcome(str, Enum):
    UNSAT = "unsat"       # contradiction confirmed by solver
    SAT = "sat"           # no contradiction found / mutually consistent
    UNKNOWN = "unknown"   # solver exceeded time budget or inconclusive


class SolverResult(BaseModel):
    """Output of the symbolic solver for a single CandidatePair."""

    model_config = ConfigDict(frozen=True)

    result_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Stable UUID4."""

    pair_id: str
    """Foreign-key reference to the CandidatePair that triggered this check."""

    backend: SolverBackend
    """Which solver produced this result."""

    outcome: SolverOutcome
    """Solver verdict: UNSAT | SAT | UNKNOWN."""

    proof_trace: Optional[str] = None
    """Human-readable solver evidence.
    Z3: unsat-core text, e.g. '(unsat-core (payment_days_30) (payment_days_15))'.
    Datalog: derivation chain, e.g. 'contradicts(C1, C2) :- ...'.
    REQUIRED when outcome == UNSAT; None otherwise is valid."""

    numeric_check: Optional[str] = None
    """Textual description of a numeric contradiction check that failed.
    E.g. '30 days (§4.2) != 15 days (§8.1) → FAIL'."""

    temporal_check: Optional[str] = None
    """Textual description of a temporal contradiction check that failed.
    E.g. 'effective_date(2024-01-01) > termination_date(2023-06-01) → FAIL'."""

    solver_input: str
    """The exact encoding sent to the solver (for auditability and reproducibility)."""

    runtime_ms: int = Field(ge=0)
    """Wall-clock time the solver took, in milliseconds."""

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @model_validator(mode="after")
    def _validate_proof_trace(self) -> "SolverResult":
        if (
            self.outcome == SolverOutcome.UNSAT
            and self.proof_trace is None
        ):
            raise ValueError(
                "proof_trace must be non-null when outcome is UNSAT; "
                "a contradiction verdict without a checkable proof trace is invalid"
            )
        return self
