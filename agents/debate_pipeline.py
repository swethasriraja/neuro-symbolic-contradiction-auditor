"""
Full Multi-Agent Debate Auditor Pipeline.

Pipeline entry point:
documents/claims -> term resolution -> FAISS retrieval -> hybrid candidate pairs (capped) -> debate loop -> Findings.
Preserves Step 3 NoDebatePipeline as a separate runnable baseline.
"""
from __future__ import annotations

from decimal import Decimal
import logging
from typing import Optional, Sequence

from agents.auditor import AuditorAgent
from agents.debate_loop import DebateLoop
from agents.defender import DefenderAgent
from agents.judge import JudgeAgent
from agents.models import DebateBudget
from agents.verifier import DeterministicVerifier
from extraction.provider import LLMProvider
from retrieval.candidate_pairs import HybridCandidatePairGenerator
from schemas.claim import Claim
from schemas.finding import Finding
from schemas.pair import CandidatePair

logger = logging.getLogger(__name__)


class DebateAuditorPipeline:
    """
    End-to-end neuro-symbolic multi-agent debate contradiction auditing pipeline.
    """

    def __init__(
        self,
        provider: LLMProvider,
        pair_generator: Optional[HybridCandidatePairGenerator] = None,
        budget: Optional[DebateBudget] = None,
        timeout_ms: int = 2000,
    ):
        self.provider = provider
        self.pair_generator = pair_generator or HybridCandidatePairGenerator()
        self.budget = budget or DebateBudget()

        # Initialize agents
        self.auditor = AuditorAgent(provider=provider)
        self.defender = DefenderAgent(provider=provider)
        self.verifier = DeterministicVerifier(timeout_ms=timeout_ms)
        self.judge = JudgeAgent(provider=provider)

        self.debate_loop = DebateLoop(
            auditor=self.auditor,
            defender=self.defender,
            verifier=self.verifier,
            judge=self.judge,
            budget=self.budget,
        )

    def audit_claims(
        self,
        claims: Sequence[Claim],
        doc_text: str,
    ) -> list[Finding]:
        """
        Audit a collection of document claims using the multi-agent debate loop.

        Args:
            claims: Extracted claims from one document.
            doc_text: Normalized document text for span verification.

        Returns:
            List of verified Findings (CONTRADICTION, CONSISTENT, or UNRESOLVED).
        """
        if len(claims) < 2:
            return []

        doc_id = claims[0].span.doc_id

        # 1. Retrieval & Hybrid Candidate Pairing (capped at max_candidate_pairs for debate)
        candidate_pairs = self.pair_generator.generate_candidate_pairs(
            claims=claims,
            apply_cap_for_debate=True,
        )
        logger.info(
            f"[DebateAuditorPipeline] Doc {doc_id[:8]}...: "
            f"Generated {len(candidate_pairs)} candidate pairs for debate."
        )

        findings: list[Finding] = []
        cumulative_doc_cost = Decimal("0")
        total_overrules = 0

        # 2. Execute Bounded Debate for Each Pair
        for i, pair in enumerate(candidate_pairs):
            finding, thread, pair_cost = self.debate_loop.run_debate(
                pair=pair,
                doc_text=doc_text,
                doc_cumulative_cost=cumulative_doc_cost,
            )
            findings.append(finding)
            cumulative_doc_cost += pair_cost
            if finding.judge_overruled:
                total_overrules += 1

        logger.info(
            f"[DebateAuditorPipeline] Finished auditing doc {doc_id[:8]}...: "
            f"Produced {len(findings)} findings. Total overrules: {total_overrules}. "
            f"Total LLM Cost: ${cumulative_doc_cost}."
        )

        return findings
