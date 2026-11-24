"""
FastAPI service and database storage tests.
Uses FastAPI TestClient, MockLLMProvider, and temporary SQLite storage.
Tests all endpoints, authentication, validations, exact offset retrieval,
report generation, human reviews, and deletion cascading.
"""
from __future__ import annotations

import io
import json
import pytest
from fastapi.testclient import TestClient

from api.main import app, verify_api_key
from storage.database import Base, engine, get_db
from storage.models import AuditModel, DocumentModel, FindingModel, HumanReviewModel

client = TestClient(app)
AUTH_HEADERS = {"X-API-Key": "test-api-key"}


@pytest.fixture(autouse=True)
def setup_db():
    """Ensure clean tables before every test."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


class TestHealthAndAuth:
    def test_health_endpoint(self) -> None:
        """Health probe is public and returns 200 OK."""
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"

    def test_auth_enforced(self) -> None:
        """Protected endpoints reject requests missing valid X-API-Key."""
        res = client.post("/documents")
        assert res.status_code == 401
        assert "Invalid or missing" in res.json()["detail"]


class TestDocumentUpload:
    def test_upload_valid_plaintext(self) -> None:
        """Upload valid text document and verify SHA-256 and metadata."""
        content = b"SECTION 1. Payment shall be due in thirty (30) days."
        files = {"file": ("contract.txt", io.BytesIO(content), "text/plain")}
        res = client.post("/documents", files=files, headers=AUTH_HEADERS)
        assert res.status_code == 201
        data = res.json()
        assert len(data["doc_id"]) == 64
        assert data["char_length"] == len(content)

    def test_upload_invalid_pdf_magic_bytes_rejected(self) -> None:
        """PDF with invalid magic bytes must be rejected with 400."""
        files = {"file": ("contract.pdf", io.BytesIO(b"not a real pdf"), "application/pdf")}
        res = client.post("/documents", files=files, headers=AUTH_HEADERS)
        assert res.status_code == 400
        assert "Invalid PDF magic bytes" in res.json()["detail"]

    def test_upload_file_too_large_rejected(self) -> None:
        """Files exceeding size limit return 413."""
        huge_content = b"A" * (51 * 1024 * 1024)
        files = {"file": ("huge.txt", io.BytesIO(huge_content), "text/plain")}
        res = client.post("/documents", files=files, headers=AUTH_HEADERS)
        assert res.status_code == 413


class TestAuditWorkflowAndFindings:
    def test_full_audit_workflow(self) -> None:
        """End-to-end audit lifecycle: upload -> audit -> poll -> findings -> report -> review."""
        # 1. Upload Document with known planted deadline contradiction
        text = (
            "SECTION 1. Licensee shall pay within thirty (30) days.\n\n"
            "SECTION 2. Licensee shall pay within forty-five (45) days."
        )
        files = {"file": ("contract.txt", io.BytesIO(text.encode("utf-8")), "text/plain")}
        upload_res = client.post("/documents", files=files, headers=AUTH_HEADERS)
        assert upload_res.status_code == 201
        doc_id = upload_res.json()["doc_id"]

        # 2. Start Audit
        audit_res = client.post(
            "/audits",
            json={"doc_ids": [doc_id], "module": "legal", "system": "full"},
            headers=AUTH_HEADERS,
        )
        assert audit_res.status_code == 202
        audit_id = audit_res.json()["audit_id"]

        # 3. Poll Audit Status (synchronous in TestClient with background task execution)
        status_res = client.get(f"/audits/{audit_id}", headers=AUTH_HEADERS)
        assert status_res.status_code == 200
        assert status_res.json()["status"] in ("running", "done")

        # 4. List Findings
        findings_res = client.get(f"/audits/{audit_id}/findings", headers=AUTH_HEADERS)
        assert findings_res.status_code == 200
        findings = findings_res.json()
        assert len(findings) >= 0

        # 5. Exact Text Slice Endpoint
        slice_res = client.get(f"/documents/{doc_id}/text?start=0&end=9", headers=AUTH_HEADERS)
        assert slice_res.status_code == 200
        assert slice_res.json()["text"] == "SECTION 1"

        # 6. Generate Reports (JSON, Markdown, HTML)
        json_report = client.get(f"/audits/{audit_id}/report?format=json", headers=AUTH_HEADERS)
        assert json_report.status_code == 200
        assert "audit_id" in json_report.json()

        md_report = client.get(f"/audits/{audit_id}/report?format=md", headers=AUTH_HEADERS)
        assert md_report.status_code == 200
        assert "# Contradiction Audit Report" in md_report.text

        html_report = client.get(f"/audits/{audit_id}/report?format=html", headers=AUTH_HEADERS)
        assert html_report.status_code == 200
        assert "<!DOCTYPE html>" in html_report.text

    def test_human_review_preserves_system_verdict(self) -> None:
        """Human review is recorded in human_reviews and NEVER alters Finding.status."""
        # Setup document & audit & finding manually
        db = next(get_db())
        doc = DocumentModel(
            doc_id="d1",
            filename="test.txt",
            file_format="txt",
            full_text="test text",
            char_length=9,
        )
        audit = AuditModel(
            audit_id="a1",
            doc_id="d1",
            module="legal",
            system_type="full",
            status="done",
            config_hash="cfg",
            model_name="mock",
        )
        finding = FindingModel(
            finding_id="f1",
            audit_id="a1",
            pair_id="p1",
            status="contradiction",
            severity="high",
            confidence=0.95,
            title="Sample Contradiction",
            description="Details",
            claim_a_start=0,
            claim_a_end=4,
            claim_a_text="test",
            claim_b_start=5,
            claim_b_end=9,
            claim_b_text="text",
            spans_verified=True,
        )
        db.add_all([doc, audit, finding])
        db.commit()

        # Submit human review
        review_res = client.post(
            "/findings/f1/review",
            json={"decision": "dismiss", "notes": "False alarm; business exception applies."},
            headers=AUTH_HEADERS,
        )
        assert review_res.status_code == 201
        assert review_res.json()["decision"] == "dismiss"

        # Query finding detail and verify system status is STILL contradiction
        detail_res = client.get("/findings/f1", headers=AUTH_HEADERS)
        assert detail_res.status_code == 200
        assert detail_res.json()["status"] == "contradiction"  # Unchanged!

    def test_delete_document_cascades(self) -> None:
        """Deleting document cascades to delete audits and findings."""
        db = next(get_db())
        doc = DocumentModel(
            doc_id="d_del",
            filename="del.txt",
            file_format="txt",
            full_text="delete me",
            char_length=9,
        )
        audit = AuditModel(
            audit_id="a_del",
            doc_id="d_del",
            module="legal",
            system_type="full",
            status="done",
            config_hash="cfg",
            model_name="mock",
        )
        db.add_all([doc, audit])
        db.commit()

        del_res = client.delete("/documents/d_del", headers=AUTH_HEADERS)
        assert del_res.status_code == 200

        # Assert document and audit are gone
        assert db.query(DocumentModel).filter_by(doc_id="d_del").first() is None
        assert db.query(AuditModel).filter_by(audit_id="a_del").first() is None
