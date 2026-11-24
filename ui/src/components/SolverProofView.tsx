import React from "react";

interface SolverProofViewProps {
  backend?: string;
  outcome?: string;
  proofTrace?: string;
  unsatCore?: string[];
}

export const SolverProofView: React.FC<SolverProofViewProps> = ({
  backend,
  outcome,
  proofTrace,
  unsatCore,
}) => {
  if (!outcome) return null;

  return (
    <div className="card" style={{ backgroundColor: "#f8fafc" }}>
      <h3 style={{ margin: "0 0 12px 0" }}>Formal Verification Proof</h3>
      <div style={{ display: "flex", gap: 16, marginBottom: 12 }}>
        <div>
          <strong>Solver Backend:</strong> <code>{backend?.toUpperCase() || "Z3"}</code>
        </div>
        <div>
          <strong>Outcome:</strong>{" "}
          <span
            style={{
              fontWeight: 700,
              color: outcome === "unsat" ? "#dc2626" : outcome === "sat" ? "#16a34a" : "#d97706",
            }}
          >
            {outcome.toUpperCase()}
          </span>
        </div>
      </div>

      {unsatCore && unsatCore.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <strong>Unsat Core (Conflicting Claims):</strong>
          <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
            {unsatCore.map((id) => (
              <span key={id} className="badge" style={{ backgroundColor: "#fee2e2", color: "#991b1b" }}>
                Claim {id}
              </span>
            ))}
          </div>
        </div>
      )}

      {proofTrace && (
        <div>
          <strong>Proof Trace / Counter-Example:</strong>
          <pre
            style={{
              background: "#1e293b",
              color: "#f8fafc",
              padding: 12,
              borderRadius: 6,
              overflowX: "auto",
              fontSize: "0.85rem",
              marginTop: 4,
            }}
          >
            {proofTrace}
          </pre>
        </div>
      )}
    </div>
  );
};
