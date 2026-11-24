"""
Unified evaluation systems interface and implementations.
- System A: SingleLLMBaseline (direct prompt, no debate, no solver)
- System B: DebateNoSolverSystem (Auditor + Defender + Judge only; solver disabled)
- System C: NeuroSymbolicSystem (full Step 4 retrieval + debate + deterministic verifier + solver)
"""
from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from agents.auditor import AuditorAgent
from agents.debate_loop import DebateLoop
from agents.defender import DefenderAgent
from agents.judge import JudgeAgent
from agents.models import DebateBudget
from agents.verifier import DeterministicVerifier, VerifierEvaluation
from extraction.provider import LLMProvider
from eval.models import EvalSystemOutput
from retrieval.candidate_pairs import HybridCandidatePairGenerator
from schemas.claim import LegalClaim, LegalClaimType
from schemas.finding import Finding, FindingStatus, Severity
from schemas.pair import CandidatePair
from schemas.solver import SolverBackend, SolverOutcome, SolverResult
from schemas.span import SourceSpan

logger = logging.getLogger(__name__)


class IEvalSystem(ABC):
    """Common evaluation interface across all benchmarked systems."""

    @property
    @abstractmethod
    def system_id(self) -> str:
        pass

    @abstractmethod
    def evaluate_document(
        self,
        doc_id: str,
        doc_text: str,
        claims: Optional[list] = None,
    ) -> EvalSystemOutput:
        pass


class SingleLLMBaseline(IEvalSystem):
    """System A: Direct single-prompt baseline over document."""

    def __init__(self, provider: LLMProvider, prompt_path: Optional[Path] = None):
        self.provider = provider
        prompt_file = prompt_path or (
            Path(__file__).parent.parent / "configs" / "prompts" / "single_llm_v1.txt"
        )
        if prompt_file.exists():
            with open(prompt_file, "r", encoding="utf-8") as f:
                self.prompt_template = f.read()
        else:
            self.prompt_template = "Identify contradictions in this text:\n{document_text}"

    @property
    def system_id(self) -> str:
        return "single_llm_baseline"

    def evaluate_document(
        self,
        doc_id: str,
        doc_text: str,
        claims: Optional[list] = None,
    ) -> EvalSystemOutput:
        start_time = time.time()
        prompt = self.prompt_template.replace("{document_text}", doc_text[:8000])

        call_record = self.provider.generate(prompt)
        latency = time.time() - start_time

        findings: list[Finding] = []
        try:
            cleaned = call_record.text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            data = json.loads(cleaned.strip())

            for i, c in enumerate(data.get("contradictions", [])):
                snip_a = c.get("snippet_a", "")
                snip_b = c.get("snippet_b", "")

                idx_a = doc_text.find(snip_a) if snip_a else 0
                idx_b = doc_text.find(snip_b) if snip_b else 0

                span_a = SourceSpan(
                    doc_id=doc_id,
                    doc_path="doc.txt",
                    char_start=idx_a if idx_a != -1 else 0,
                    char_end=(idx_a + len(snip_a)) if idx_a != -1 else len(snip_a),
                    text_snippet=snip_a,
                )
                span_b = SourceSpan(
                    doc_id=doc_id,
                    doc_path="doc.txt",
                    char_start=idx_b if idx_b != -1 else 0,
                    char_end=(idx_b + len(snip_b)) if idx_b != -1 else len(snip_b),
                    text_snippet=snip_b,
                )

                dummy_solver_res = SolverResult(
                    pair_id=f"single_llm_pair_{i}",
                    backend=SolverBackend.Z3,
                    solver_input="single_llm_no_solver",
                    outcome=SolverOutcome.UNKNOWN,
                    runtime_ms=0,
                )

                findings.append(
                    Finding(
                        pair_id=f"single_llm_pair_{i}",
                        solver_result_id=dummy_solver_res.result_id,
                        solver_outcome=SolverOutcome.UNKNOWN,
                        status=FindingStatus.CONTRADICTION if c.get("status") == "contradiction" else FindingStatus.UNRESOLVED,
                        severity=Severity.HIGH,
                        confidence=float(c.get("confidence", 0.8)),
                        title=c.get("title", f"Contradiction {i}"),
                        description=c.get("description", ""),
                        claim_a_span=span_a,
                        claim_b_span=span_b,
                        spans_verified=(idx_a != -1 and idx_b != -1),
                    )
                )
        except Exception as e:
            logger.warning(f"[SingleLLMBaseline] Failed to parse output: {e}")

        return EvalSystemOutput(
            system_id=self.system_id,
            doc_id=doc_id,
            findings=findings,
            total_tokens=call_record.prompt_tokens + call_record.completion_tokens,
            total_cost_usd=float(call_record.cost_usd),
            latency_seconds=latency,
            llm_calls_count=1,
        )


class DebateNoSolverSystem(IEvalSystem):
    """System B: Multi-Agent Debate with Solver Disabled (Judge LLM alone decides)."""

    def __init__(self, provider: LLMProvider, budget: Optional[DebateBudget] = None):
        self.provider = provider
        self.budget = budget or DebateBudget(max_rounds=3)
        self.auditor = AuditorAgent(provider)
        self.defender = DefenderAgent(provider)
        self.judge = JudgeAgent(provider)
        self.pair_generator = HybridCandidatePairGenerator()

    @property
    def system_id(self) -> str:
        return "debate_no_solver"

    def evaluate_document(
        self,
        doc_id: str,
        doc_text: str,
        claims: Optional[list] = None,
    ) -> EvalSystemOutput:
        start_time = time.time()
        if not claims:
            return EvalSystemOutput(system_id=self.system_id, doc_id=doc_id, findings=[])

        pairs = self.pair_generator.generate_candidate_pairs(claims)
        findings: list[Finding] = []
        total_tokens = 0
        total_cost = 0.0
        llm_calls = 0

        # Run debate per candidate pair without deterministic solver verification
        for pair in pairs:
            # Auditor turn
            auditor_arg, a_msg = self.auditor.argue(
                pair=pair,
                context_text=doc_text,
                thread_id="t_no_solver",
                round_number=1,
            )
            total_tokens += a_msg.prompt_tokens + a_msg.completion_tokens
            total_cost += float(a_msg.cost_usd)
            llm_calls += 1

            # Defender turn
            defender_arg, d_msg = self.defender.defend(
                pair=pair,
                auditor_arg=auditor_arg,
                context_text=doc_text,
                thread_id="t_no_solver",
                round_number=1,
            )
            total_tokens += d_msg.prompt_tokens + d_msg.completion_tokens
            total_cost += float(d_msg.cost_usd)
            llm_calls += 1

            # Mock evaluation without solver
            dummy_solver_res = SolverResult(
                pair_id=pair.pair_id,
                backend=SolverBackend.Z3,
                solver_input="no_solver_eval",
                outcome=SolverOutcome.UNKNOWN,
                runtime_ms=0,
            )
            eval_mock = VerifierEvaluation(
                solver_result=dummy_solver_res,
                spans_verified=True,
                reconciliation_valid=(defender_arg.reconciliation_type != "none"),
                reconciliation_reason=defender_arg.explanation,
                is_decisive=True,
            )

            # Judge turn
            judge_verdict, j_msg = self.judge.adjudicate(
                pair=pair,
                debate_record_text=f"Auditor: {auditor_arg.assertion}\nDefender: {defender_arg.explanation}",
                verifier_eval=eval_mock,
                thread_id="t_no_solver",
                round_number=1,
            )
            total_tokens += j_msg.prompt_tokens + j_msg.completion_tokens
            total_cost += float(j_msg.cost_usd)
            llm_calls += 1

            # Final status comes directly from Judge (no code gate overrule)
            status_str = judge_verdict.proposed_status.lower()
            if status_str == "contradiction":
                status = FindingStatus.CONTRADICTION
            elif status_str == "consistent":
                status = FindingStatus.CONSISTENT
            else:
                status = FindingStatus.UNRESOLVED

            findings.append(
                Finding(
                    pair_id=pair.pair_id,
                    solver_result_id=dummy_solver_res.result_id,
                    solver_outcome=SolverOutcome.UNKNOWN,
                    status=status,
                    severity=Severity.HIGH if status == FindingStatus.CONTRADICTION else Severity.INFO,
                    confidence=judge_verdict.confidence,
                    title=judge_verdict.title,
                    description=judge_verdict.verdict_summary,
                    claim_a_span=pair.claim_a.span,
                    claim_b_span=pair.claim_b.span,
                    spans_verified=True,
                )
            )

        latency = time.time() - start_time
        return EvalSystemOutput(
            system_id=self.system_id,
            doc_id=doc_id,
            findings=findings,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            latency_seconds=latency,
            llm_calls_count=llm_calls,
        )


class NeuroSymbolicSystem(IEvalSystem):
    """System C: Full Neuro-Symbolic Debate & Verification Loop (Step 4)."""

    def __init__(self, provider: LLMProvider, budget: Optional[DebateBudget] = None):
        self.provider = provider
        self.budget = budget or DebateBudget(max_rounds=3)
        self.debate_loop = DebateLoop(
            auditor=AuditorAgent(provider),
            defender=DefenderAgent(provider),
            verifier=DeterministicVerifier(),
            judge=JudgeAgent(provider),
            budget=self.budget,
        )
        self.pair_generator = HybridCandidatePairGenerator()

    @property
    def system_id(self) -> str:
        return "neuro_symbolic_full"

    def evaluate_document(
        self,
        doc_id: str,
        doc_text: str,
        claims: Optional[list] = None,
    ) -> EvalSystemOutput:
        start_time = time.time()
        if not claims:
            return EvalSystemOutput(system_id=self.system_id, doc_id=doc_id, findings=[])

        pairs = self.pair_generator.generate_candidate_pairs(claims)
        findings: list[Finding] = []
        total_tokens = 0
        total_cost = 0.0
        llm_calls = 0

        for pair in pairs:
            finding, thread, cost = self.debate_loop.run_debate(
                pair=pair,
                doc_text=doc_text,
                doc_cumulative_cost=total_cost,
            )
            findings.append(finding)
            total_cost += float(cost)
            for msg in thread.messages:
                total_tokens += msg.prompt_tokens + msg.completion_tokens
                llm_calls += 1

        latency = time.time() - start_time
        return EvalSystemOutput(
            system_id=self.system_id,
            doc_id=doc_id,
            findings=findings,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            latency_seconds=latency,
            llm_calls_count=llm_calls,
        )
