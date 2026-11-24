"""
SQLAlchemy 2.0 database models.
Covers: documents, chunks, claims, audits, candidate_pairs, solver_results,
debate_threads, debate_messages, findings, human_reviews, and llm_calls.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from storage.database import Base


class DocumentModel(Base):
    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_format: Mapped[str] = mapped_column(String(10), nullable=False)
    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    char_length: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    chunks: Mapped[list["ChunkModel"]] = relationship("ChunkModel", back_populates="document", cascade="all, delete-orphan")
    claims: Mapped[list["ClaimModel"]] = relationship("ClaimModel", back_populates="document", cascade="all, delete-orphan")
    audits: Mapped[list["AuditModel"]] = relationship("AuditModel", back_populates="document", cascade="all, delete-orphan")


class ChunkModel(Base):
    __tablename__ = "chunks"

    chunk_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    doc_id: Mapped[str] = mapped_column(String(64), ForeignKey("documents.doc_id", ondelete="CASCADE"), nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(50), nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    section_heading: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    page_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    document: Mapped["DocumentModel"] = relationship("DocumentModel", back_populates="chunks")


class ClaimModel(Base):
    __tablename__ = "claims"

    claim_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(64), ForeignKey("documents.doc_id", ondelete="CASCADE"), nullable=False)
    module: Mapped[str] = mapped_column(String(20), nullable=False)
    claim_type: Mapped[str] = mapped_column(String(50), nullable=False)
    predicate: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    document: Mapped["DocumentModel"] = relationship("DocumentModel", back_populates="claims")


class AuditModel(Base):
    __tablename__ = "audits"

    audit_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    doc_id: Mapped[str] = mapped_column(String(64), ForeignKey("documents.doc_id", ondelete="CASCADE"), nullable=False)
    module: Mapped[str] = mapped_column(String(20), nullable=False)
    system_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    pairs_total: Mapped[int] = mapped_column(Integer, default=0)
    pairs_completed: Mapped[int] = mapped_column(Integer, default=0)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, default=42)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    document: Mapped["DocumentModel"] = relationship("DocumentModel", back_populates="audits")
    candidate_pairs: Mapped[list["CandidatePairModel"]] = relationship("CandidatePairModel", back_populates="audit", cascade="all, delete-orphan")
    findings: Mapped[list["FindingModel"]] = relationship("FindingModel", back_populates="audit", cascade="all, delete-orphan")
    llm_calls: Mapped[list["LLMCallModel"]] = relationship("LLMCallModel", back_populates="audit", cascade="all, delete-orphan")


class CandidatePairModel(Base):
    __tablename__ = "candidate_pairs"

    pair_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    audit_id: Mapped[str] = mapped_column(String(36), ForeignKey("audits.audit_id", ondelete="CASCADE"), nullable=False)
    claim_a_id: Mapped[str] = mapped_column(String(36), nullable=False)
    claim_b_id: Mapped[str] = mapped_column(String(36), nullable=False)
    similarity_score: Mapped[float] = mapped_column(Float, nullable=False)
    retrieval_method: Mapped[str] = mapped_column(String(50), nullable=False)

    audit: Mapped["AuditModel"] = relationship("AuditModel", back_populates="candidate_pairs")
    solver_result: Mapped[Optional["SolverResultModel"]] = relationship("SolverResultModel", back_populates="pair", uselist=False, cascade="all, delete-orphan")
    debate_thread: Mapped[Optional["DebateThreadModel"]] = relationship("DebateThreadModel", back_populates="pair", uselist=False, cascade="all, delete-orphan")
    finding: Mapped[Optional["FindingModel"]] = relationship("FindingModel", back_populates="pair", uselist=False, cascade="all, delete-orphan")


class SolverResultModel(Base):
    __tablename__ = "solver_results"

    result_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    pair_id: Mapped[str] = mapped_column(String(64), ForeignKey("candidate_pairs.pair_id", ondelete="CASCADE"), nullable=False)
    backend: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    runtime_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    proof_trace: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unsat_core_json: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    solver_input: Mapped[str] = mapped_column(Text, nullable=False)

    pair: Mapped["CandidatePairModel"] = relationship("CandidatePairModel", back_populates="solver_result")


class DebateThreadModel(Base):
    __tablename__ = "debate_threads"

    thread_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    pair_id: Mapped[str] = mapped_column(String(64), ForeignKey("candidate_pairs.pair_id", ondelete="CASCADE"), nullable=False)
    rounds_used: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    final_verdict: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    pair: Mapped["CandidatePairModel"] = relationship("CandidatePairModel", back_populates="debate_thread")
    messages: Mapped[list["DebateMessageModel"]] = relationship("DebateMessageModel", back_populates="thread", cascade="all, delete-orphan")


class DebateMessageModel(Base):
    __tablename__ = "debate_messages"

    message_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    thread_id: Mapped[str] = mapped_column(String(36), ForeignKey("debate_threads.thread_id", ondelete="CASCADE"), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    sender: Mapped[str] = mapped_column(String(20), nullable=False)
    argument_text: Mapped[str] = mapped_column(Text, nullable=False)
    cited_claim_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)

    thread: Mapped["DebateThreadModel"] = relationship("DebateThreadModel", back_populates="messages")


class FindingModel(Base):
    __tablename__ = "findings"

    finding_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_id: Mapped[str] = mapped_column(String(36), ForeignKey("audits.audit_id", ondelete="CASCADE"), nullable=False)
    pair_id: Mapped[str] = mapped_column(String(64), ForeignKey("candidate_pairs.pair_id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    claim_a_start: Mapped[int] = mapped_column(Integer, nullable=False)
    claim_a_end: Mapped[int] = mapped_column(Integer, nullable=False)
    claim_a_text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_b_start: Mapped[int] = mapped_column(Integer, nullable=False)
    claim_b_end: Mapped[int] = mapped_column(Integer, nullable=False)
    claim_b_text: Mapped[str] = mapped_column(Text, nullable=False)
    spans_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    judge_overruled: Mapped[bool] = mapped_column(Boolean, default=False)
    overrule_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    unresolved_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    audit: Mapped["AuditModel"] = relationship("AuditModel", back_populates="findings")
    pair: Mapped["CandidatePairModel"] = relationship("CandidatePairModel", back_populates="finding")
    reviews: Mapped[list["HumanReviewModel"]] = relationship("HumanReviewModel", back_populates="finding", cascade="all, delete-orphan")


class HumanReviewModel(Base):
    __tablename__ = "human_reviews"

    review_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    finding_id: Mapped[str] = mapped_column(String(36), ForeignKey("findings.finding_id", ondelete="CASCADE"), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False)
    reviewer_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    finding: Mapped["FindingModel"] = relationship("FindingModel", back_populates="reviews")


class LLMCallModel(Base):
    __tablename__ = "llm_calls"

    call_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    audit_id: Mapped[str] = mapped_column(String(36), ForeignKey("audits.audit_id", ondelete="CASCADE"), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    output_text: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    seed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    temperature: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    audit: Mapped["AuditModel"] = relationship("AuditModel", back_populates="llm_calls")
