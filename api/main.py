"""
FastAPI application for the Neuro-Symbolic Contradiction Auditor.
Exposes endpoints for document upload, audit orchestration, findings inspection,
reports generation, human review tracking, and health checks.
"""
from __future__ import annotations

import os
os.environ["DISABLE_SQLALCHEMY_CEXT"] = "1"

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from api.reports import ReportGenerator
from api.schemas import (
    AuditCreateRequest,
    AuditCreateResponse,
    AuditStatusResponse,
    DebateTranscriptMessageResponse,
    DebateTranscriptResponse,
    DocumentUploadResponse,
    ExactTextResponse,
    FindingDetailResponse,
    FindingSummaryResponse,
    HumanReviewRequest,
    HumanReviewResponse,
)
from api.worker import AuditWorker
from ingestion.base import ParsedDocument
from ingestion.docx import DocxParser
from ingestion.html import HTMLParser
from ingestion.pdf import PDFParser
from ingestion.txt import PlainTextParser
from storage.database import Base, engine, get_db
from storage.models import (
    AuditModel,
    DebateThreadModel,
    DocumentModel,
    FindingModel,
    HumanReviewModel,
)

# Initialize database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Neuro-Symbolic Contradiction Auditor API",
    version="0.1.0",
    description="Formal contradiction detection for legal contracts and financial filings.",
)

# Security & CORS
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_KEY = os.getenv("API_KEY", "test-api-key")


def verify_api_key(x_api_key: Optional[str] = Header(None)) -> str:
    """Enforce API-key authentication for protected routes."""
    if not x_api_key or x_api_key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header.",
        )
    return x_api_key


worker = AuditWorker()


@app.get("/health", tags=["System"])
def health_check() -> dict:
    """Public healthcheck probe for container orchestration."""
    return {
        "status": "healthy",
        "service": "neuro-symbolic-auditor",
        "version": "0.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post(
    "/documents",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Documents"],
)
async def upload_document(
    file: UploadFile = File(...),
    auth: str = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> DocumentUploadResponse:
    """Upload PDF, DOCX, or HTML document. Validates content magic bytes and extracts text."""
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File exceeds 50MB size limit.")

    filename = file.filename or "upload.txt"
    ext = filename.lower().split(".")[-1]

    # Content verification
    if ext == "pdf":
        if not content.startswith(b"%PDF-"):
            raise HTTPException(status_code=400, detail="Invalid PDF magic bytes.")
        doc: ParsedDocument = PDFParser().parse_bytes(content, doc_path=filename)
    elif ext == "docx":
        if not content.startswith(b"PK\x03\x04"):
            raise HTTPException(status_code=400, detail="Invalid DOCX magic bytes.")
        doc = DocxParser().parse_bytes(content, doc_path=filename)
    elif ext in ("html", "htm"):
        doc = HTMLParser().parse_bytes(content, doc_path=filename)
    elif ext == "txt":
        doc = PlainTextParser().parse_bytes(content, doc_path=filename)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format '{ext}'. Must be pdf, docx, html, or txt.",
        )

    doc_model = DocumentModel(
        doc_id=doc.doc_id,
        filename=filename,
        file_format=ext,
        full_text=doc.full_text,
        char_length=len(doc.full_text),
    )
    db.merge(doc_model)
    db.commit()

    return DocumentUploadResponse(
        doc_id=doc.doc_id,
        filename=filename,
        file_format=ext,
        char_length=len(doc.full_text),
        created_at=datetime.now(timezone.utc),
    )


@app.post(
    "/audits",
    response_model=AuditCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Audits"],
)
def create_audit(
    request: AuditCreateRequest,
    background_tasks: BackgroundTasks,
    auth: str = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> AuditCreateResponse:
    """Submit an asynchronous audit job for a target document."""
    doc_id = request.doc_ids[0]
    doc = db.query(DocumentModel).filter_by(doc_id=doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found.")

    audit = AuditModel(
        doc_id=doc_id,
        module=request.module,
        system_type=request.system,
        status="queued",
        config_hash=hashlib.sha256(str(request.config_overrides).encode()).hexdigest(),
        model_name="claude-3-5-sonnet-20241022",
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)

    background_tasks.add_task(worker.process_audit_job, audit.audit_id)

    return AuditCreateResponse(
        audit_id=audit.audit_id,
        status="queued",
        created_at=audit.created_at,
    )


@app.get(
    "/audits/{audit_id}",
    response_model=AuditStatusResponse,
    tags=["Audits"],
)
def get_audit_status(
    audit_id: str,
    auth: str = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> AuditStatusResponse:
    """Query status, progress, and resource utilization for an audit."""
    audit = db.query(AuditModel).filter_by(audit_id=audit_id).first()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found.")

    return AuditStatusResponse(
        audit_id=audit.audit_id,
        doc_id=audit.doc_id,
        module=audit.module,
        system_type=audit.system_type,
        status=audit.status,
        progress=audit.progress,
        pairs_total=audit.pairs_total,
        pairs_completed=audit.pairs_completed,
        total_tokens=audit.total_tokens,
        total_cost_usd=audit.total_cost_usd,
        error_message=audit.error_message,
        started_at=audit.started_at,
        completed_at=audit.completed_at,
    )


@app.get(
    "/audits/{audit_id}/findings",
    response_model=list[FindingSummaryResponse],
    tags=["Findings"],
)
def list_findings(
    audit_id: str,
    verdict: Optional[str] = Query(None, pattern="^(contradiction|consistent|unresolved)$"),
    severity: Optional[str] = Query(None),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    auth: str = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> list[FindingSummaryResponse]:
    """List findings for an audit, filterable by verdict, severity, and confidence."""
    query = db.query(FindingModel).filter_by(audit_id=audit_id)
    if verdict:
        query = query.filter_by(status=verdict)
    if severity:
        query = query.filter_by(severity=severity)
    if min_confidence > 0.0:
        query = query.filter(FindingModel.confidence >= min_confidence)

    findings = query.all()
    return [
        FindingSummaryResponse(
            finding_id=f.finding_id,
            pair_id=f.pair_id,
            status=f.status,
            severity=f.severity,
            confidence=f.confidence,
            title=f.title,
            spans_verified=f.spans_verified,
            judge_overruled=f.judge_overruled,
        )
        for f in findings
    ]


@app.get(
    "/findings/{finding_id}",
    response_model=FindingDetailResponse,
    tags=["Findings"],
)
def get_finding_detail(
    finding_id: str,
    auth: str = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> FindingDetailResponse:
    """Retrieve complete finding details, conflicting text spans, and formal solver proof."""
    f = db.query(FindingModel).filter_by(finding_id=finding_id).first()
    if not f:
        raise HTTPException(status_code=404, detail="Finding not found.")

    solver_outcome = None
    solver_backend = None
    proof_trace = None
    unsat_core = None

    if f.pair and f.pair.solver_result:
        sr = f.pair.solver_result
        solver_outcome = sr.outcome
        solver_backend = sr.backend
        proof_trace = sr.proof_trace
        unsat_core = sr.unsat_core_json

    return FindingDetailResponse(
        finding_id=f.finding_id,
        audit_id=f.audit_id,
        pair_id=f.pair_id,
        status=f.status,
        severity=f.severity,
        confidence=f.confidence,
        title=f.title,
        description=f.description,
        claim_a_text=f.claim_a_text,
        claim_a_start=f.claim_a_start,
        claim_a_end=f.claim_a_end,
        claim_b_text=f.claim_b_text,
        claim_b_start=f.claim_b_start,
        claim_b_end=f.claim_b_end,
        spans_verified=f.spans_verified,
        judge_overruled=f.judge_overruled,
        overrule_reason=f.overrule_reason,
        unresolved_reason=f.unresolved_reason,
        solver_outcome=solver_outcome,
        solver_backend=solver_backend,
        solver_proof_trace=proof_trace,
        unsat_core=unsat_core,
    )


@app.get(
    "/findings/{finding_id}/transcript",
    response_model=DebateTranscriptResponse,
    tags=["Findings"],
)
def get_debate_transcript(
    finding_id: str,
    auth: str = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> DebateTranscriptResponse:
    """Fetch complete multi-agent debate history for a finding."""
    finding = db.query(FindingModel).filter_by(finding_id=finding_id).first()
    if not finding or not finding.pair or not finding.pair.debate_thread:
        raise HTTPException(status_code=404, detail="Debate transcript not found.")

    thread = finding.pair.debate_thread
    msgs = [
        DebateTranscriptMessageResponse(
            message_id=m.message_id,
            round_number=m.round_number,
            sender=m.sender,
            argument_text=m.argument_text,
            cited_claim_ids=m.cited_claim_ids or [],
            cost_usd=m.cost_usd,
        )
        for m in sorted(thread.messages, key=lambda x: (x.round_number, x.message_id))
    ]

    return DebateTranscriptResponse(
        thread_id=thread.thread_id,
        pair_id=thread.pair_id,
        rounds_used=thread.rounds_used,
        status=thread.status,
        final_verdict=thread.final_verdict,
        messages=msgs,
    )


@app.get(
    "/documents/{doc_id}/text",
    response_model=ExactTextResponse,
    tags=["Documents"],
)
def get_exact_document_text(
    doc_id: str,
    start: int = Query(..., ge=0),
    end: int = Query(..., ge=0),
    auth: str = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> ExactTextResponse:
    """Returns exact text from stored source document at [start:end] char offsets."""
    doc = db.query(DocumentModel).filter_by(doc_id=doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if start > end or end > len(doc.full_text):
        raise HTTPException(status_code=400, detail="Invalid offset range.")

    return ExactTextResponse(
        doc_id=doc.doc_id,
        start=start,
        end=end,
        text=doc.full_text[start:end],
    )


@app.get(
    "/audits/{audit_id}/report",
    tags=["Audits"],
)
def get_audit_report(
    audit_id: str,
    format: str = Query("json", pattern="^(json|html|md)$"),
    auth: str = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> Response:
    """Generate standalone contradiction report in JSON, Markdown, or HTML."""
    audit = db.query(AuditModel).filter_by(audit_id=audit_id).first()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found.")

    doc = db.query(DocumentModel).filter_by(doc_id=audit.doc_id).first()
    findings = db.query(FindingModel).filter_by(audit_id=audit.audit_id).all()

    if format == "json":
        data = ReportGenerator.generate_json_report(audit, doc, findings)
        return Response(content=json.dumps(data, indent=2), media_type="application/json")
    elif format == "md":
        md = ReportGenerator.generate_markdown_report(audit, doc, findings)
        return Response(content=md, media_type="text/markdown")
    else:
        html = ReportGenerator.generate_html_report(audit, doc, findings)
        return Response(content=html, media_type="text/html")


@app.post(
    "/findings/{finding_id}/review",
    response_model=HumanReviewResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Human Review"],
)
def submit_human_review(
    finding_id: str,
    request: HumanReviewRequest,
    auth: str = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> HumanReviewResponse:
    """
    Record human reviewer decision (confirm | dismiss | needs_more_info).
    Stored separately. NEVER modifies the formal system verdict.
    """
    finding = db.query(FindingModel).filter_by(finding_id=finding_id).first()
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found.")

    review = HumanReviewModel(
        finding_id=finding.finding_id,
        decision=request.decision,
        reviewer_notes=request.notes,
    )
    db.add(review)
    db.commit()
    db.refresh(review)

    return HumanReviewResponse(
        review_id=review.review_id,
        finding_id=review.finding_id,
        decision=review.decision,
        notes=review.reviewer_notes,
        reviewed_at=review.reviewed_at,
    )


@app.delete(
    "/documents/{doc_id}",
    tags=["Documents"],
)
def delete_document(
    doc_id: str,
    auth: str = Depends(verify_api_key),
    db: Session = Depends(get_db),
) -> dict:
    """Cascade delete document and all derived chunks, claims, audits, and findings."""
    doc = db.query(DocumentModel).filter_by(doc_id=doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    db.delete(doc)
    db.commit()
    return {"status": "deleted", "doc_id": doc_id}
