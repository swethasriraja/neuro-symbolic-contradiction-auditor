"""
schemas — shared data contracts for the Neuro-Symbolic Contradiction Auditor.

This package has ZERO imports from other project packages.
Every other package (ingestion, extraction, symbolic, agents, retrieval, eval, api)
depends on this package; this package depends on nothing internal.

Public API
----------
SourceSpan          — provenance anchor: doc_id, page, section, char offsets, snippet
Chunk               — ingestion unit (text window from a document)
LegalClaimType      — enum: 9 legal claim categories
LegalClaim          — an extracted claim from a contract
FinancialMetric     — enum: 15 financial metric categories
SourceType          — enum: narrative | table | footnote
FinancialClaim      — an extracted claim from a financial document
Claim               — discriminated union: LegalClaim | FinancialClaim
ClaimModule         — enum: legal | financial
ClaimSet            — typed container for one document's claims
CandidatePair       — a retrieval-flagged pair of claims for contradiction checking
AgentRole           — enum: auditor | defender | verifier | judge
DebateMessage       — a single agent turn in the debate (with full LLM telemetry)
DebateThread        — full debate: messages, rounds used, final verdict
ThreadStatus        — enum: open | closed | timed_out
SolverBackend       — enum: z3 | datalog
SolverOutcome       — enum: unsat | sat | unknown
SolverResult        — symbolic solver output (proof_trace required when UNSAT)
Severity            — enum: critical | high | medium | low | info
FindingStatus       — enum: contradiction | consistent | unresolved
Finding             — final auditor output with provenance, verdict, and review flags
"""

from schemas.span import SourceSpan
from schemas.chunk import Chunk, ChunkType
from schemas.claim import (
    LegalClaim,
    LegalClaimType,
    FinancialClaim,
    FinancialMetric,
    SourceType,
    Claim,
    ClaimModule,
    ClaimSet,
)
from schemas.pair import CandidatePair
from schemas.debate import AgentRole, DebateMessage, DebateThread, ThreadStatus
from schemas.solver import SolverBackend, SolverOutcome, SolverResult
from schemas.finding import Finding, FindingStatus, Severity

__all__ = [
    # span
    "SourceSpan",
    # chunk
    "Chunk",
    "ChunkType",
    # claim
    "LegalClaim",
    "LegalClaimType",
    "FinancialClaim",
    "FinancialMetric",
    "SourceType",
    "Claim",
    "ClaimModule",
    "ClaimSet",
    # pair
    "CandidatePair",
    # debate
    "AgentRole",
    "DebateMessage",
    "DebateThread",
    "ThreadStatus",
    # solver
    "SolverBackend",
    "SolverOutcome",
    "SolverResult",
    # finding
    "Finding",
    "FindingStatus",
    "Severity",
]
