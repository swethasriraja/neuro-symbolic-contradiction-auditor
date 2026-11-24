# System Limitations & Failure Modes

This document provides a transparent analysis of supported vs unsupported constraint patterns, known failure modes, evaluation caveats, and operational boundaries.

---

## 1. Supported vs. Unsupported Patterns

### 1.1 Supported Claim & Constraint Types
- **Deadlines & Durations**: Notice periods, cure periods, termination lead times, payment windows (e.g. 30 days vs 45 days).
- **Payment Amounts & Precedence**: Flat license fees, minimum purchase commitments, tier structures, and priority ordering.
- **Financial Arithmetic & Ratios**:
  - Growth percentages ($(\text{New} - \text{Old}) / \text{Old}$).
  - Table column/row summations ($\sum \text{items} == \text{Total}$).
  - Margins and ratios ($\text{Operating Income} / \text{Revenue}$).
  - Explicit rounding tolerances ($\pm 0.1\%$).
- **Deontic Horn Logic**:
  - Mutual exclusion of obligation (`shall`) vs prohibition (`shall not`) on the same party and action.
  - Amendment overrides ("Section X of Amendment No. 1 amends and supersedes Section Y").
- **Defined-Term Scope Checking**:
  - Explicit glossary conflicts (conflicting definitions for the same term across clauses).
  - Business Days vs Calendar Days unit mismatch detection.
  - Conditional scope exceptions ("unless", "except as provided in Section Z").

### 1.2 Unsupported Constraint Types (v1 Scope Boundaries)
- **Subjective & Standard-of-Care Clauses**: Obligations conditioned on "commercially reasonable efforts", "best efforts", or "material adverse effect" cannot be encoded in classical first-order SMT.
- **Complex Indemnification Scopes**: Open-ended third-party IP indemnity with discretionary carve-outs.
- **Cross-Jurisdictional Conflicts of Law**: Multi-tiered conflict-of-law doctrines (e.g. New York law governing general clauses while Delaware law governs equity transfers).
- **Non-Linear Financial Formulas**: Black-Scholes valuations, discounted cash flow (DCF) modeling, or actuarial estimates.

---

## 2. Known Failure Modes

1. **Scanned Documents & OCR Degradation**:
   - The ingestion layer expects machine-readable text in PDFs, DOCX, and HTML.
   - Scanned image PDFs without embedded text layers fail cleanly with an informative error. Optical Character Recognition (OCR) is not included in v1.
2. **Irregular & Nested Financial Tables**:
   - Tables with merged cells, multiple nested sub-headers, or non-standard formatting can cause column alignment shifts. In such cases, table sums may fail to extract, causing pairs to fall back to `UNRESOLVED`.
3. **LLM Extraction Misses**:
   - The symbolic solver can only prove or disprove claims that the extraction layer successfully identified. If an LLM extractor misses a subtle clause in a lengthy 200-page agreement, the contradiction will not be proposed for debate.
4. **Defined-Term Appendix Separation**:
   - In agreements where defined terms are listed in a distant Annex or Schedule that does not carry standard "Section" or "Article" headers, defined terms may not associate with downstream clauses.
5. **Language Support**:
   - v1 prompt templates and regex tokenizers are calibrated exclusively for English commercial agreements and SEC filings. Non-English contracts are unsupported.
6. **Cost Scaling on Massive Filings**:
   - Running full multi-agent debate across filings exceeding 500 pages requires strict candidate capping (`max_candidate_pairs: 25`) to prevent budget exhaustion.

---

## 3. Evaluation Caveats

- **Synthetic Injections vs. Real-World Nuance**:
  - Public benchmarks (CUAD, ContractNLI, FinQA) lack dense internal contradiction ground truth within single documents. While synthetic injection provides exact character-offset verification, real-world drafting errors are often messier and more ambiguously phrased.
- **Metric Interpretation**:
  - Precision, Recall, and F1 are evaluated using character-span Intersection-over-Union ($\text{IoU} \ge 0.5$). Predictions overlapping by less than 50% are treated as misses.
- **Dual Handling of `UNRESOLVED`**:
  - Standard reporting treats `UNRESOLVED` as a detection miss ($FN$). Filtered reporting excludes unresolved items to measure accuracy when expert referral is utilized.

---

## 4. Legal & Financial Disclaimer

> **IMPORTANT**: The Neuro-Symbolic Contradiction Auditor is an automated verification and auditing tool intended solely to assist professional legal and financial reviewers. It does **not** provide legal advice, financial advice, or formal audit opinions. Every finding flagged by the system must be independently reviewed and verified by qualified legal counsel or certified financial accountants before taking any contractual or regulatory action.
