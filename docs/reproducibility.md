# Reproducibility Guide

This guide details the complete reproducibility checklist, exact execution commands, configuration hashes, and resource requirements to reproduce all results in the Neuro-Symbolic Contradiction Auditor evaluation report.

---

## 1. Reproducibility Checklist

| Dimension | Specification | Configuration Location |
| :--- | :--- | :--- |
| **Python Version** | `3.11.15` (CPython) | `pyproject.toml` |
| **Random Seed** | `42` (Fixed across all runners) | `configs/default.yaml`, `configs/eval.yaml` |
| **Sampling Temperature** | `0.0` (Deterministic greedy decoding) | `configs/default.yaml` |
| **Default Model** | `claude-3-5-sonnet-20241022` | `configs/default.yaml` |
| **Local Embedder** | `sentence-transformers/all-MiniLM-L6-v2` | `configs/default.yaml` |
| **Vector Index** | `faiss.IndexFlatIP` (Cosine similarity) | `retrieval/faiss_index.py` |
| **Solver Backend** | `z3-solver` (`Z3 4.13.0+`) | `symbolic/numeric_temporal.py` |
| **Prompts Version** | `v1` (Versioned static prompt files) | `configs/prompts/*.txt` |
| **Cache Key Formula** | `sha256(doc_hash + system_id + config_hash + seed)` | `eval/metrics/cache.py` |

---

## 2. Evaluation Reproduction Commands

### 2.1 Dry-Run Evaluation (Zero API Spend)
To verify the entire evaluation harness without making any network calls:
```bash
python -m eval.run --config configs/eval.yaml --dry-run --pilot
```
- **Dataset**: 5-document synthetic pilot suite (legal deadline, deontic modality, financial growth, hard negative rounding, clean document).
- **Systems Evaluated**: `single_llm`, `debate_no_solver`, `neuro_symbolic_full`.
- **Cost**: **$0.00** (Uses `MockLLMProvider`).
- **Runtime**: ~5 seconds.

### 2.2 Live Pilot Evaluation (5 Documents)
To run a live evaluation of the pilot suite using the Anthropic API:
```bash
python -m eval.run --config configs/eval.yaml --no-dry-run --pilot
```
- **Estimated Cost**: **$0.68 – $1.50 USD**.
- **Expected Runtime**: 2 to 3 minutes.
- **Budget Guard**: Automatically terminates if cumulative spend reaches `hard_cost_limit_usd` ($5.00).

### 2.3 Running Controlled Ablations
Each ablation config isolates exactly one architectural component:
```bash
# 1. Ablation: Solver Disabled (Multi-agent debate only)
python -m eval.run --config configs/eval.yaml --dry-run --system debate_no_solver

# 2. Ablation: Debate Disabled (Direct candidate pairs to solver)
python -m eval.run --config configs/eval.yaml --dry-run --system no_debate

# 3. Ablation: Single-LLM Baseline (Direct prompting)
python -m eval.run --config configs/eval.yaml --dry-run --system single
```

---

## 3. Public Dataset Preparation
Large public evaluation benchmarks (CUAD, ContractNLI, FinQA, TAT-QA) are **not** downloaded automatically during installation.
To fetch sample fixtures:
```bash
python scripts/download_eval_datasets.py --dataset all --sample 10
```
Public dataset fixtures are mirrored in `eval/data/fixtures/` and verified by unit tests in `tests/test_eval.py`.
