import React, { useEffect, useState } from "react";
import { api } from "../api/client";
import { FindingSummary } from "../api/types";
import { Badge } from "../components/Badge";

interface Props {
  auditId: string;
  onSelectFinding: (findingId: string) => void;
  onBack: () => void;
}

export const FindingsListPage: React.FC<Props> = ({ auditId, onSelectFinding, onBack }) => {
  const [findings, setFindings] = useState<FindingSummary[]>([]);
  const [verdictFilter, setVerdictFilter] = useState<string>("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadFindings();
  }, [auditId, verdictFilter]);

  const loadFindings = async () => {
    setLoading(true);
    try {
      const res = await api.getFindings(auditId, {
        verdict: verdictFilter || undefined,
      });
      setFindings(res);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <div>
          <button className="btn btn-secondary" onClick={onBack} style={{ marginRight: 12 }}>
            ← Back to Upload
          </button>
          <h2 style={{ display: "inline-block", margin: 0 }}>Audit Findings (Audit #{auditId.slice(0, 8)})</h2>
        </div>
        <div>
          <a
            href={api.getReportUrl(auditId, "json")}
            download
            className="btn btn-secondary"
            style={{ marginRight: 8 }}
          >
            Download JSON
          </a>
          <a
            href={api.getReportUrl(auditId, "md")}
            download
            className="btn btn-secondary"
            style={{ marginRight: 8 }}
          >
            Download Markdown
          </a>
          <a href={api.getReportUrl(auditId, "html")} target="_blank" className="btn btn-primary" rel="noreferrer">
            View HTML Report
          </a>
        </div>
      </div>

      <div className="card" style={{ display: "flex", gap: 16, alignItems: "center" }}>
        <strong>Filter by Verdict:</strong>
        <select
          value={verdictFilter}
          onChange={(e) => setVerdictFilter(e.target.value)}
          style={{ padding: "6px 12px" }}
        >
          <option value="">All Findings ({findings.length})</option>
          <option value="contradiction">Contradictions Only</option>
          <option value="unresolved">Unresolved / Needs Review</option>
          <option value="consistent">Consistent Pairs</option>
        </select>
      </div>

      {loading ? (
        <div className="card">Loading findings...</div>
      ) : findings.length === 0 ? (
        <div className="card">No findings match the selected criteria.</div>
      ) : (
        findings.map((f) => (
          <div
            key={f.finding_id}
            className="card"
            style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}
          >
            <div>
              <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 8 }}>
                <Badge type="status" value={f.status} />
                <Badge type="severity" value={f.severity} />
                <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
                  Confidence: {(f.confidence * 100).toFixed(0)}%
                </span>
                {f.judge_overruled && (
                  <span className="badge" style={{ backgroundColor: "#eff6ff", color: "#1e40af" }}>
                    Formal Overrule
                  </span>
                )}
              </div>
              <h3 style={{ margin: "4px 0" }}>{f.title}</h3>
            </div>
            <button className="btn btn-primary" onClick={() => onSelectFinding(f.finding_id)}>
              Inspect Evidence →
            </button>
          </div>
        ))
      )}
    </div>
  );
};
