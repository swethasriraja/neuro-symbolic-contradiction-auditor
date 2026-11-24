import React, { useState } from "react";
import { UploadPage } from "./pages/UploadPage";
import { FindingsListPage } from "./pages/FindingsListPage";
import { EvidenceDetailPage } from "./pages/EvidenceDetailPage";

export const App: React.FC = () => {
  const [currentAuditId, setCurrentAuditId] = useState<string | null>(null);
  const [currentFindingId, setCurrentFindingId] = useState<string | null>(null);

  return (
    <div>
      <nav className="navbar">
        <span className="navbar-brand">⚖️ Neuro-Symbolic Contradiction Auditor</span>
        <span style={{ fontSize: "0.85rem", color: "var(--text-muted)" }}>
          Formal Z3 Proofs & Multi-Agent Debate
        </span>
      </nav>

      <main className="container">
        {!currentAuditId ? (
          <UploadPage onAuditStarted={(id) => setCurrentAuditId(id)} />
        ) : !currentFindingId ? (
          <FindingsListPage
            auditId={currentAuditId}
            onSelectFinding={(id) => setCurrentFindingId(id)}
            onBack={() => setCurrentAuditId(null)}
          />
        ) : (
          <EvidenceDetailPage
            findingId={currentFindingId}
            onBack={() => setCurrentFindingId(null)}
          />
        )}
      </main>
    </div>
  );
};
