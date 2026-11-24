import React from "react";
import { FindingStatus, Severity } from "../api/types";

interface BadgeProps {
  type: "status" | "severity";
  value: FindingStatus | Severity | string;
}

export const Badge: React.FC<BadgeProps> = ({ type, value }) => {
  const val = value.toLowerCase();

  if (type === "status") {
    if (val === "contradiction") {
      return (
        <span className="badge badge-contradiction" role="status" aria-label="Contradiction">
          🛑 CONTRADICTION
        </span>
      );
    }
    if (val === "unresolved") {
      return (
        <span className="badge badge-unresolved" role="status" aria-label="Needs Human Review">
          ⚠️ UNRESOLVED (Needs Review)
        </span>
      );
    }
    return (
      <span className="badge badge-consistent" role="status" aria-label="Consistent">
        ✅ CONSISTENT
      </span>
    );
  }

  // Severity
  return (
    <span className="badge" style={{ backgroundColor: "#e2e8f0", color: "#334155" }}>
      {value.toUpperCase()}
    </span>
  );
};
