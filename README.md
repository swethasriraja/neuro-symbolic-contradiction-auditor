# Neuro-Symbolic Contradiction Auditor (v1)

> **Core Principle**: LLM agents propose and debate candidate contradictions; symbolic solvers (Z3 / Datalog) formally decide. Every verdict is anchored by checkable character offsets in source text.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Tests: 114 Passed](https://img.shields.io/badge/tests-114%20passed-brightgreen.svg)]()
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

The **Neuro-Symbolic Contradiction Auditor** audits internal contradictions in legal contracts and financial statements. Rather than relying on LLMs as sole judges—which frequently hallucinate inconsistencies or miss numerical subtleties—this system uses a bounded multi-agent debate loop (Auditor vs. Defender) verified by deterministic Z3 SMT solvers and Horn clause deontic logic.

---

## Scope

### Included in v1
- **Module A (Legal)**: Internal contradictions within **one** legal contract:
  - Conflicting deadlines, notice periods, and cure periods.
  - Payment amounts, due dates, and fee schedules.
  - Obligation vs prohibition conflicts on identical parties and actions.
  - Conflicting governing law clauses and conflicting defined-term scopes.
- **Module B (Financial)**: Narrative text vs tabular disclosures within **one** annual report or filing:
  - Narrative growth rates vs table-derived percentages.
  - Narrative totals vs table arithmetic sums.
  - Metric margin and scale consistency.
- **Deterministic Verification**: Exact character offset tracking (`text[start:end] == snippet`).
- **Bounded Debate**: Maximum 3 rounds with token and cost budgets.
- **Hard-Coded Code Gate**: Verdict enums are strictly `CONTRADICTION | CONSISTENT | UNRESOLVED`. Contradictions are confirmed **only** if the symbolic solver proves `UNSAT`.
- **FastAPI Backend & React TypeScript UI**: Interactive evidence viewer with exact offset highlighting, proof trace inspection, and multi-format report export.

### Explicitly v2 (Not in v1)
- Cross-document contradiction checks (e.g. Master Services Agreement vs Statement of Work, or 10-K vs 10-Q).
- Multi-party multi-contract portfolio reconciliation.

---

## Quickstart

### 1. Prerequisites & Environment Setup
Copy the environment template and configure your secrets:
```bash
cp .env.example .env
```
Ensure `.env` contains:
```env
GEMINI_API_KEY=your-api-key-here
API_KEY=test-api-key
DATABASE_URL=postgresql://auditor_user:auditor_pass@db:5432/auditor_db
```

### 2. One-Command Docker Deployment
Start the entire stack (FastAPI backend, PostgreSQL database, and React UI):
```bash
docker compose up -d --build
```
- **Web UI Evidence Viewer**: [http://localhost:3000](http://localhost:3000)
- **API Health Check**: [http://localhost:8000/health](http://localhost:8000/health)
- **Swagger API Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

### 3. Local Development Mode
```bash
# Install dependencies
pip install -e ".[dev]"

# Run full test suite (114 tests, mock provider, zero API calls)
make test

# Run dry-run evaluation on 5-document pilot suite
make eval-dry-run

# Run local API server
make run
```

---

## Example: Detected Contradiction

### Input Contract Excerpt
```text
SECTION 4. PAYMENT TERMS.
Licensee shall remit payment of all accrued licensing fees within thirty (30) days of receipt of invoice.
...
SECTION 12. TERMINATION REMEDIES.
Upon termination, all outstanding fees shall become immediately payable within forty-five (45) days of termination date.
```

### Terminal Finding JSON Output
```json
{
  "finding_id": "84a1e95b-3b36-4762-b430-c3d6904ad6cb",
  "pair_id": "pair_001",
  "status": "contradiction",
  "severity": "high",
  "confidence": 0.95,
  "title": "Payment deadline conflict (30 days vs 45 days)",
  "description": "Section 4 mandates payment within 30 days while Section 12 specifies 45 days for identical licensee obligations.",
  "claim_a_span": {
    "doc_id": "d2f4...e18a",
    "char_start": 26,
    "char_end": 128,
    "text_snippet": "Licensee shall remit payment of all accrued licensing fees within thirty (30) days of receipt of invoice."
  },
  "claim_b_span": {
    "doc_id": "d2f4...e18a",
    "char_start": 164,
    "char_end": 283,
    "text_snippet": "Upon termination, all outstanding fees shall become immediately payable within forty-five (45) days of termination date."
  },
  "spans_verified": true,
  "solver_outcome": "unsat",
  "solver_backend": "z3",
  "proof_trace": "[Z3 Proof]: Constraints (deadline == 30) AND (deadline == 45) proven mutually UNSAT."
}
```

---

## Security & Privacy Notice
> **Data Handling Notice**: Document snippets and extracted claims are sent to the configured LLM provider (Google Gemini) for semantic extraction and multi-agent debate. Document text is never logged to application logs or console at `INFO` level and is stored securely in the database.
