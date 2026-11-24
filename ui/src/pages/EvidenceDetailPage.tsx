import React, { useEffect, useState } from "react";
import { api } from "../api/client";
import { DebateTranscript, FindingDetail } from "../api/types";
import { Badge } from "../components/Badge";
import { DebateTranscriptView } from "../components/DebateTranscriptView";
import { SideBySideView } from "../components/SideBySideView";
import { SolverProofView } from "../components/SolverProofView";

interface Props {
  findingId: string;
  onBack: () => void;
}

export const EvidenceDetailPage: React.FC<Props> = ({ findingId, onBack }) => {
  const [finding, setFinding] = useState<FindingDetail | null>(null);
  const [transcript, setTranscript] = useState<DebateTranscript | null>(null);
  const [reviewDecision, setReviewDecision] = useState<"confirm" | "dismiss" | "needs_more_info">("confirm");
  const [reviewNotes, setReviewNotes] = useState("");
  const [reviewStatus, setReviewStatus] = useState<string | null>(null);

  useEffect(() => {
    loadDetail();
  }, [findingId]);

  const loadDetail = async () => {
    try {
      const f = await api.getFindingDetail(findingId);
      setFinding(f);
      const t = await api.getDebateTranscript(findingId).catch(() => null);
      setTranscript(t);
    } catch (err) {
      console.error(err);
    }
  };

  const handleReviewSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await api.submitReview(findingId, {
        decision: reviewDecision,
        notes: reviewNotes,
      });
      setReviewStatus(`Decision '${res.decision}' recorded. Formal system verdict remains immutable.`);
    } catch (err) {
      setReviewStatus("Failed to submit review.");
    }
  };

  if (!finding) return <div className="card">Loading evidence details...</div>;

  return (
    <div>
      <button className="btn btn-secondary" onClick={onBack} style={{ marginBottom: 16 }}>
        ← Back to Findings
      </button>

      {/* Header Card */}
      <div className="card">
        <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 8 }}>
          <Badge type="status" value={finding.status} />
          <Badge type="severity" value={finding.severity} />
          <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
            Confidence: {(finding.confidence * 100).toFixed(0)}%
          </span>
        </div>
        <h2 style={{ margin: "8px 0" }}>{finding.title}</h2>
        <p style={{ margin: "4px 0", color: "var(--text-muted)" }}>{finding.description}</p>

        {finding.judge_overruled && (
          <div className="alert-overruled">
            <strong>⚠️ Formal Code Gate Overruled Judge:</strong> {finding.overrule_reason}
          </div>
        )}

        {finding.status === "unresolved" && (
          <div className="alert-unresolved">
            <strong>🔍 Human Review Required:</strong> {finding.unresolved_reason || "Verification inconclusive."}
          </div>
        )}
      </div>

      {/* Side-by-Side Highlighting */}
      <SideBySideView
        clauseAText={finding.claim_a_text}
        clauseAStart={finding.claim_a_start}
        clauseAEnd={finding.claim_a_end}
        clauseBText={finding.claim_b_text}
        clauseBStart={finding.claim_b_start}
        clauseBEnd={finding.claim_b_end}
        spansVerified={finding.spans_verified}
      />

      {/* Symbolic Solver Proof Trace */}
      <SolverProofView
        backend={finding.solver_backend}
        outcome={finding.solver_outcome}
        proofTrace={finding.solver_proof_trace}
        unsatCore={finding.unsat_core}
      />

      {/* Multi-Agent Debate Transcript */}
      {transcript && <DebateTranscriptView transcript={transcript} />}

      {/* Human Review Form */}
      <div className="card">
        <h3>Human Auditor Decision</h3>
        <p style={{ color: "var(--text-muted)", fontSize: "0.9rem" }}>
          Record your expert legal/financial adjudication. Decisions are logged separately for quality tracking and
          never mutate the formal system verdict.
        </p>

        {reviewStatus && (
          <div style={{ padding: 12, background: "#dcfce7", color: "#166534", borderRadius: 4, marginBottom: 12 }}>
            {reviewStatus}
          </div>
        )}

        <form onSubmit={handleReviewSubmit}>
          <div style={{ display: "flex", gap: 24, marginBottom: 16 }}>
            <label>
              <input
                type="radio"
                name="decision"
                value="confirm"
                checked={reviewDecision === "confirm"}
                onChange={() => setReviewDecision("confirm")}
              />{" "}
              Confirm Contradiction
            </label>
            <label>
              <input
                type="radio"
                name="decision"
                value="dismiss"
                checked={reviewDecision === "dismiss"}
                onChange={() => setReviewDecision("dismiss")}
              />{" "}
              Dismiss (False Alarm)
            </label>
            <label>
              <input
                type="radio"
                name="decision"
                value="needs_more_info"
                checked={reviewDecision === "needs_more_info"}
                onChange={() => setReviewDecision("needs_more_info")}
              />{" "}
              Needs More Information
            </label>
          </div>

          <div style={{ marginBottom: 16 }}>
            <textarea
              placeholder="Add reviewer notes or contractual context..."
              value={reviewNotes}
              onChange={(e) => setReviewNotes(e.target.value)}
              style={{ width: "100%", height: 80, padding: 8, borderRadius: 4, border: "1px solid var(--border-color)" }}
            />
          </div>

          <button type="submit" className="btn btn-primary">
            Submit Review
          </button>
        </form>
      </div>
    </div>
  );
};
