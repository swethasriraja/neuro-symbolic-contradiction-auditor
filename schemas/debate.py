"""
DebateMessage and DebateThread — structured agent communication.

Design decisions
----------------
1. round_number is capped at 3 (max_rounds) at the schema level.
   This is a hard contract invariant, not just a config default.

2. Full LLM telemetry is embedded on every DebateMessage — model, tokens,
   cost_usd (Decimal for exactness), latency_ms. This is non-negotiable per
   the engineering rules: every LLM call must be logged with full cost and
   latency data.

3. claim_ids (FK-style, not embedded Claim objects) keeps messages compact
   and avoids duplicating potentially large claim data across the debate log.

4. DebateThread.final_verdict links to a SolverResult — the solver always has
   the final word; agent consensus alone is never sufficient.

5. A CLOSED thread without a final_verdict raises ValidationError.
   Closing a debate without a solver result is invalid.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schemas.solver import SolverResult


class AgentRole(str, Enum):
    AUDITOR = "auditor"
    DEFENDER = "defender"
    VERIFIER = "verifier"
    JUDGE = "judge"


class ThreadStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    TIMED_OUT = "timed_out"


class DebateMessage(BaseModel):
    """A single agent turn within a debate thread."""

    model_config = ConfigDict(frozen=True)

    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Stable UUID4."""

    thread_id: str
    """Foreign-key reference to the parent DebateThread."""

    round_number: int = Field(ge=1, le=3)
    """Debate round. Must be 1, 2, or 3. Schema-level hard limit."""

    sender: AgentRole
    """The agent that produced this message."""

    claim_ids: list[str] = Field(min_length=1)
    """IDs of the claims being argued in this message. Must be non-empty."""

    argument: str
    """Natural-language argument text from the agent."""

    structured: dict[str, Any] = Field(default_factory=dict)
    """Machine-readable assertion payload (agent-specific schema; Step 4)."""

    # ── LLM telemetry (required on every message) ─────────────────────────
    model: str
    """LLM model identifier, e.g. 'claude-3-5-sonnet-20241022'."""

    prompt_tokens: int = Field(ge=0)
    """Number of tokens in the prompt sent to the LLM."""

    completion_tokens: int = Field(ge=0)
    """Number of tokens in the LLM completion."""

    cost_usd: Decimal = Field(ge=Decimal("0"))
    """Exact cost in USD for this LLM call. Decimal avoids float rounding."""

    latency_ms: int = Field(ge=0)
    """Wall-clock latency for the LLM call in milliseconds."""
    # ──────────────────────────────────────────────────────────────────────

    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class DebateThread(BaseModel):
    """
    A complete debate over one CandidatePair.

    Lifecycle: OPEN → (CLOSED | TIMED_OUT)
    A CLOSED thread must have a final_verdict (SolverResult).
    rounds_used is capped at 3 (schema-level invariant).
    """

    model_config = ConfigDict(frozen=False)
    # Mutable: messages are appended as the debate progresses.

    thread_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Stable UUID4."""

    pair_id: str
    """Foreign-key reference to the CandidatePair being debated."""

    messages: list[DebateMessage] = Field(default_factory=list)
    """Ordered list of agent messages. Appended each round."""

    rounds_used: int = Field(ge=0, le=3, default=0)
    """Number of debate rounds completed. 0–3."""

    status: ThreadStatus = ThreadStatus.OPEN

    final_verdict: Optional[SolverResult] = None
    """Solver result that closed this debate.
    Required when status == CLOSED; must be None when OPEN or TIMED_OUT."""

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    closed_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _validate_closed_thread(self) -> "DebateThread":
        if (
            self.status == ThreadStatus.CLOSED
            and self.final_verdict is None
        ):
            raise ValueError(
                "A CLOSED DebateThread must have a final_verdict (SolverResult); "
                "closing a debate without a solver result is invalid"
            )
        return self
