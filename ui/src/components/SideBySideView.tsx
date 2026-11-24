import React from "react";
import { SpanHighlighter } from "./SpanHighlighter";

interface SideBySideProps {
  clauseAText: string;
  clauseAStart: number;
  clauseAEnd: number;
  clauseBText: string;
  clauseBStart: number;
  clauseBEnd: number;
  spansVerified: boolean;
}

export const SideBySideView: React.FC<SideBySideProps> = ({
  clauseAText,
  clauseAStart,
  clauseAEnd,
  clauseBText,
  clauseBStart,
  clauseBEnd,
  spansVerified,
}) => {
  return (
    <div className="comparison-grid">
      <div className="clause-card">
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
          <strong>Clause A (Source Text)</strong>
          <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
            Offset [{clauseAStart} : {clauseAEnd}]
          </span>
        </div>
        <SpanHighlighter
          fullText={clauseAText}
          charStart={clauseAStart}
          charEnd={clauseAEnd}
          isVerified={spansVerified}
        />
      </div>

      <div className="clause-card">
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
          <strong>Clause B (Source Text)</strong>
          <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
            Offset [{clauseBStart} : {clauseBEnd}]
          </span>
        </div>
        <SpanHighlighter
          fullText={clauseBText}
          charStart={clauseBStart}
          charEnd={clauseBEnd}
          isVerified={spansVerified}
        />
      </div>
    </div>
  );
};
