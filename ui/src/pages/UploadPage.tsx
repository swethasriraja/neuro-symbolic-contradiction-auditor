import React, { useState } from "react";
import { api } from "../api/client";
import { AuditStatusResponse } from "../api/types";

interface Props {
  onAuditStarted: (auditId: string) => void;
}

export const UploadPage: React.FC<Props> = ({ onAuditStarted }) => {
  const [file, setFile] = useState<File | null>(null);
  const [module, setModule] = useState<"legal" | "financial">("legal");
  const [system, setSystem] = useState<"full" | "no_debate">("full");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusInfo, setStatusInfo] = useState<AuditStatusResponse | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) return;

    setLoading(true);
    setError(null);

    try {
      // 1. Upload Document
      const uploadRes = await api.uploadDocument(file);

      // 2. Start Audit
      const auditRes = await api.createAudit({
        doc_ids: [uploadRes.doc_id],
        module,
        system,
      });

      // 3. Poll Status
      const pollInterval = setInterval(async () => {
        try {
          const s = await api.getAuditStatus(auditRes.audit_id);
          setStatusInfo(s);
          if (s.status === "done" || s.status === "failed") {
            clearInterval(pollInterval);
            setLoading(false);
            if (s.status === "done") {
              onAuditStarted(auditRes.audit_id);
            }
          }
        } catch (err) {
          clearInterval(pollInterval);
          setLoading(false);
        }
      }, 1000);
    } catch (err: any) {
      setError(err.message || "Upload failed");
      setLoading(false);
    }
  };

  return (
    <div className="card" style={{ maxWidth: 600, margin: "0 auto" }}>
      <h2>Start Contradiction Audit</h2>
      <p style={{ color: "var(--text-muted)" }}>
        Upload a legal contract or financial statement to audit internal contradictions using formal Z3
        solvers and multi-agent debate.
      </p>

      {error && <div style={{ color: "red", marginBottom: 16 }}>{error}</div>}

      <form onSubmit={handleSubmit}>
        <div style={{ marginBottom: 16 }}>
          <label style={{ display: "block", fontWeight: 600, marginBottom: 8 }}>Select Document:</label>
          <input
            type="file"
            accept=".pdf,.docx,.html,.htm,.txt"
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            required
          />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 16 }}>
          <div>
            <label style={{ display: "block", fontWeight: 600, marginBottom: 8 }}>Domain Module:</label>
            <select
              value={module}
              onChange={(e) => setModule(e.target.value as any)}
              style={{ width: "100%", padding: 8 }}
            >
              <option value="legal">Legal Contracts</option>
              <option value="financial">Financial Statements</option>
            </select>
          </div>
          <div>
            <label style={{ display: "block", fontWeight: 600, marginBottom: 8 }}>Audit System:</label>
            <select
              value={system}
              onChange={(e) => setSystem(e.target.value as any)}
              style={{ width: "100%", padding: 8 }}
            >
              <option value="full">Full Neuro-Symbolic Debate</option>
              <option value="no_debate">Deterministic Rules + Solver</option>
            </select>
          </div>
        </div>

        <button type="submit" className="btn btn-primary" disabled={loading || !file} style={{ width: "100%" }}>
          {loading ? "Running Audit..." : "Upload and Begin Audit"}
        </button>
      </form>

      {statusInfo && (
        <div style={{ marginTop: 24, padding: 16, background: "#f8fafc", borderRadius: 6, border: "1px solid #e2e8f0" }}>
          <div>
            <strong>Status:</strong>{" "}
            <span style={{ color: statusInfo.status === "failed" ? "#dc2626" : statusInfo.status === "done" ? "#16a34a" : "#ca8a04", fontWeight: "bold" }}>
              {statusInfo.status.toUpperCase()}
            </span>{" "}
            | <strong>Pairs:</strong> {statusInfo.pairs_completed} / {statusInfo.pairs_total} | <strong>Cost:</strong> ${statusInfo.total_cost_usd.toFixed(4)}
          </div>
          {statusInfo.status === "failed" && (
            <div
              style={{
                marginTop: 12,
                padding: "10px 14px",
                background: "#fee2e2",
                border: "1px solid #f87171",
                borderRadius: 6,
                color: "#991b1b",
                fontSize: "0.9rem",
              }}
            >
              <strong>Audit Error:</strong> {statusInfo.error_message || "The audit failed during processing."}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
