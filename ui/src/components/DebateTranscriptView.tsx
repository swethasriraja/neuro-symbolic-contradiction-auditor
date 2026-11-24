import React, { useState } from "react";
import { DebateTranscript as DebateTranscriptType } from "../api/types";

interface Props {
  transcript?: DebateTranscriptType;
}

export const DebateTranscriptView: React.FC<Props> = ({ transcript }) => {
  const [isOpen, setIsOpen] = useState(true);

  if (!transcript || !transcript.messages || transcript.messages.length === 0) {
    return <div className="card">No debate messages recorded.</div>;
  }

  return (
    <div className="card">
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          cursor: "pointer",
        }}
        onClick={() => setIsOpen(!isOpen)}
      >
        <h3 style={{ margin: 0 }}>
          Multi-Agent Debate History ({transcript.messages.length} turns, {transcript.rounds_used} rounds)
        </h3>
        <button className="btn btn-secondary">{isOpen ? "Hide Debate" : "Show Debate"}</button>
      </div>

      {isOpen && (
        <div style={{ marginTop: 20 }}>
          {transcript.messages.map((m) => (
            <div key={m.message_id} className="timeline-item">
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                <strong>
                  Round {m.round_number} — {m.sender.toUpperCase()}
                </strong>
                <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
                  ${m.cost_usd.toFixed(4)}
                </span>
              </div>
              <p style={{ margin: "4px 0 8px 0" }}>{m.argument_text}</p>
              {m.cited_claim_ids && m.cited_claim_ids.length > 0 && (
                <div style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
                  Cited Claims: {m.cited_claim_ids.join(", ")}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
