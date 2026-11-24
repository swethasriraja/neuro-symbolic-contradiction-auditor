"""
Audit report generator.
Generates comprehensive contradiction auditing reports in JSON, Markdown, and HTML.
Includes side-by-side clause quotations, proof traces, severity tags, and unresolved review flags.
"""
from __future__ import annotations

import json
from typing import Any
from storage.models import AuditModel, DocumentModel, FindingModel


class ReportGenerator:
    """Generates multi-format contradiction audit reports."""

    @staticmethod
    def generate_json_report(audit: AuditModel, doc: DocumentModel, findings: list[FindingModel]) -> dict[str, Any]:
        """Generate structured JSON report."""
        return {
            "audit_id": audit.audit_id,
            "document": {
                "doc_id": doc.doc_id,
                "filename": doc.filename,
                "char_length": doc.char_length,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
            },
            "audit_metadata": {
                "module": audit.module,
                "system_type": audit.system_type,
                "status": audit.status,
                "model_name": audit.model_name,
                "seed": audit.seed,
                "total_tokens": audit.total_tokens,
                "total_cost_usd": audit.total_cost_usd,
                "pairs_total": audit.pairs_total,
                "pairs_completed": audit.pairs_completed,
            },
            "findings": [
                {
                    "finding_id": f.finding_id,
                    "pair_id": f.pair_id,
                    "status": f.status,
                    "severity": f.severity,
                    "confidence": f.confidence,
                    "title": f.title,
                    "description": f.description,
                    "clause_a": {
                        "text": f.claim_a_text,
                        "char_start": f.claim_a_start,
                        "char_end": f.claim_a_end,
                    },
                    "clause_b": {
                        "text": f.claim_b_text,
                        "char_start": f.claim_b_start,
                        "char_end": f.claim_b_end,
                    },
                    "spans_verified": f.spans_verified,
                    "judge_overruled": f.judge_overruled,
                    "overrule_reason": f.overrule_reason,
                    "unresolved_reason": f.unresolved_reason,
                    "solver_trace": f.pair.solver_result.proof_trace if f.pair and f.pair.solver_result else None,
                    "unsat_core": f.pair.solver_result.unsat_core_json if f.pair and f.pair.solver_result else None,
                }
                for f in findings
            ],
        }

    @staticmethod
    def generate_markdown_report(audit: AuditModel, doc: DocumentModel, findings: list[FindingModel]) -> str:
        """Generate GitHub-flavored Markdown report."""
        lines = [
            f"# Contradiction Audit Report: {doc.filename}",
            f"**Audit ID**: `{audit.audit_id}`  ",
            f"**Status**: `{audit.status.upper()}`  ",
            f"**Module**: `{audit.module.upper()}` | **System**: `{audit.system_type}`  ",
            f"**Model**: `{audit.model_name}` (Seed: {audit.seed})  ",
            f"**Resource Usage**: {audit.total_tokens:,} tokens (~${audit.total_cost_usd:.4f})  ",
            "",
            "---",
            "",
            "## Summary of Findings",
            f"- **Total Pairs Evaluated**: {audit.pairs_total}",
            f"- **Confirmed Contradictions**: {sum(1 for f in findings if f.status == 'contradiction')}",
            f"- **Consistent / Reconciled Pairs**: {sum(1 for f in findings if f.status == 'consistent')}",
            f"- **Unresolved Flags (Human Review Required)**: {sum(1 for f in findings if f.status == 'unresolved')}",
            "",
            "---",
            "",
            "## Detailed Findings",
        ]

        if not findings:
            lines.append("No findings generated.")
            return "\n".join(lines)

        for i, f in enumerate(findings, 1):
            badge = "🔴 CONTRADICTION" if f.status == "contradiction" else ("🟡 UNRESOLVED" if f.status == "unresolved" else "🟢 CONSISTENT")
            lines.extend([
                f"### {i}. {f.title} ({badge})",
                f"- **Severity**: `{f.severity.upper()}` | **Confidence**: `{f.confidence:.2f}`",
                f"- **Description**: {f.description}",
                "",
                "#### Conflicting / Evaluated Clauses (Side-by-Side):",
                "| Clause A (Source Text) | Clause B (Source Text) |",
                "| :--- | :--- |",
                f"| *[{f.claim_a_start}:{f.claim_a_end}]* {f.claim_a_text} | *[{f.claim_b_start}:{f.claim_b_end}]* {f.claim_b_text} |",
                "",
            ])

            if f.pair and f.pair.solver_result:
                sr = f.pair.solver_result
                lines.extend([
                    "#### Symbolic Solver Verification:",
                    f"- **Solver Backend**: `{sr.backend.upper()}`",
                    f"- **Outcome**: `{sr.outcome.upper()}` ({sr.runtime_ms} ms)",
                ])
                if sr.proof_trace:
                    lines.append(f"```\n[Proof Trace]\n{sr.proof_trace}\n```")
                if sr.unsat_core_json:
                    lines.append(f"- **Unsat Core**: `{sr.unsat_core_json}`")

            if f.judge_overruled:
                lines.append(f"> ⚠️ **Judge Overruled by Formal Verification**: {f.overrule_reason}")

            if f.unresolved_reason:
                lines.append(f"> 🔍 **Human Review Note**: {f.unresolved_reason}")

            lines.append("\n---\n")

        return "\n".join(lines)

    @staticmethod
    def generate_html_report(audit: AuditModel, doc: DocumentModel, findings: list[FindingModel]) -> str:
        """Generate standalone styled HTML report."""
        md_text = ReportGenerator.generate_markdown_report(audit, doc, findings)
        # Clean HTML container with modern responsive styling
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Audit Report - {doc.filename}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #1e293b; max-width: 1000px; margin: 40px auto; padding: 0 20px; }}
    h1, h2, h3, h4 {{ color: #0f172a; }}
    table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
    th, td {{ border: 1px solid #cbd5e1; padding: 12px; text-align: left; vertical-align: top; }}
    th {{ background-color: #f8fafc; }}
    pre {{ background: #f1f5f9; padding: 12px; border-radius: 6px; overflow-x: auto; }}
    blockquote {{ border-left: 4px solid #3b82f6; margin: 16px 0; padding-left: 16px; color: #475569; }}
    .badge {{ display: inline-block; padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 0.85em; }}
    .contradiction {{ background-color: #fee2e2; color: #991b1b; }}
    .unresolved {{ background-color: #fef3c7; color: #92400e; }}
    .consistent {{ background-color: #dcfce7; color: #166534; }}
  </style>
</head>
<body>
  <div class="content">
    <pre style="white-space: pre-wrap; font-family: inherit;">{md_text}</pre>
  </div>
</body>
</html>
"""
