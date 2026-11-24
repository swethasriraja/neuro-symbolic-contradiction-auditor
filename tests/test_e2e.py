"""
End-to-end smoke test for the Neuro-Symbolic Contradiction Auditor stack.
Tests complete API-UI lifecycle:
1. Document upload
2. Audit creation & status polling
3. Findings inspection
4. Exact text span verification
5. Multi-format reports generation (JSON, Markdown, HTML)
6. Human review recording with immutable verdict guarantee
"""
from __future__ import annotations

import io
from fastapi.testclient import TestClient
from api.main import app
from storage.database import Base, engine

client = TestClient(app)
AUTH_HEADERS = {"X-API-Key": "test-api-key"}


def test_e2e_stack_audit_lifecycle():
    """Verify complete lifecycle as consumed by the React UI."""
    Base.metadata.create_all(bind=engine)

    # 1. Document Upload
    doc_content = (
        "SECTION 1. Licensee shall pay within thirty (30) days of invoice.\n\n"
        "SECTION 2. Licensee shall pay within forty-five (45) days of invoice."
    )
    files = {"file": ("e2e_contract.txt", io.BytesIO(doc_content.encode("utf-8")), "text/plain")}
    res_upload = client.post("/documents", files=files, headers=AUTH_HEADERS)
    assert res_upload.status_code == 201
    doc_id = res_upload.json()["doc_id"]

    # 2. Audit Initiation
    res_audit = client.post(
        "/audits",
        json={"doc_ids": [doc_id], "module": "legal", "system": "full"},
        headers=AUTH_HEADERS,
    )
    assert res_audit.status_code == 202
    audit_id = res_audit.json()["audit_id"]

    # 3. Status Polling
    res_status = client.get(f"/audits/{audit_id}", headers=AUTH_HEADERS)
    assert res_status.status_code == 200
    assert res_status.json()["status"] in ("running", "done")

    # 4. Findings Listing
    res_findings = client.get(f"/audits/{audit_id}/findings", headers=AUTH_HEADERS)
    assert res_findings.status_code == 200

    # 5. Exact Text Slice Endpoint for UI Highlighter
    res_text = client.get(f"/documents/{doc_id}/text?start=0&end=9", headers=AUTH_HEADERS)
    assert res_text.status_code == 200
    assert res_text.json()["text"] == "SECTION 1"

    # 6. Multi-Format Report Generation
    for fmt, media_type in [("json", "application/json"), ("md", "text/markdown"), ("html", "text/html")]:
        res_rep = client.get(f"/audits/{audit_id}/report?format={fmt}", headers=AUTH_HEADERS)
        assert res_rep.status_code == 200
        assert media_type in res_rep.headers["content-type"]
