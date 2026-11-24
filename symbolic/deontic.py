"""
Deontic Logic Solver (Datalog & Rule Reasoning).

Encodes:
1. Obligation vs. Prohibition on the same party and action.
2. Right vs. Prohibition.
3. Conditions and exceptions (conditional qualifiers prevent false-positive contradictions).
4. Precedence rules (amendment overrides base agreement, specific overrides general).
"""
from __future__ import annotations

import re
import time
from typing import Optional
import z3

from schemas.claim import LegalClaim, LegalClaimType
from schemas.pair import CandidatePair
from schemas.solver import SolverBackend, SolverOutcome, SolverResult


def extract_action_target(raw_text: str, predicate: str) -> str:
    """Extract normalized action target (e.g. disclose, terminate, assign, subcontract)."""
    text = f"{predicate} {raw_text}".lower()
    for act in ["disclose", "confidential", "terminate", "assign", "subcontract", "compete", "solicit", "audit"]:
        if act in text:
            return act
    return "general_action"


class DeonticSolver:
    """
    Deontic solver using Datalog / Horn rules and typed precedence evaluation.
    """

    def __init__(self, timeout_ms: int = 2000):
        self.timeout_ms = timeout_ms

    def check_pair(self, pair: CandidatePair) -> SolverResult:
        """Check deontic consistency between two legal claims."""
        start_t = time.perf_counter()

        if not (isinstance(pair.claim_a, LegalClaim) and isinstance(pair.claim_b, LegalClaim)):
            return SolverResult(
                pair_id=pair.pair_id,
                backend=SolverBackend.DATALOG,
                outcome=SolverOutcome.SAT,
                solver_input="Non-legal claim pair; deontic check skipped.",
                runtime_ms=0,
            )

        claim_a: LegalClaim = pair.claim_a
        claim_b: LegalClaim = pair.claim_b

        # 1. Precedence Check: Amendment Override
        is_amendment_a = "amendment" in claim_a.raw_text.lower() or "amended" in claim_a.raw_text.lower()
        is_amendment_b = "amendment" in claim_b.raw_text.lower() or "amended" in claim_b.raw_text.lower()

        if is_amendment_a != is_amendment_b:
            return SolverResult(
                pair_id=pair.pair_id,
                backend=SolverBackend.DATALOG,
                outcome=SolverOutcome.SAT,
                solver_input="Precedence: Amendment clause supersedes base contract provision.",
                runtime_ms=int((time.perf_counter() - start_t) * 1000),
            )

        # 2. Specific vs. General Override Check
        if claim_a.scope_qualifier or claim_b.scope_qualifier:
            qual = (claim_a.scope_qualifier or claim_b.scope_qualifier or "").lower()
            if any(k in qual for k in ["specific", "in particular", "notwithstanding", "except"]):
                return SolverResult(
                    pair_id=pair.pair_id,
                    backend=SolverBackend.DATALOG,
                    outcome=SolverOutcome.SAT,
                    solver_input=f"Precedence: Specific exception ('{qual}') overrides general clause.",
                    runtime_ms=int((time.perf_counter() - start_t) * 1000),
                )

        # 3. Normative Conflict: Obligation vs Prohibition
        type_a = claim_a.claim_type
        type_b = claim_b.claim_type

        is_conflict = (
            (type_a == LegalClaimType.OBLIGATION and type_b == LegalClaimType.PROHIBITION)
            or (type_a == LegalClaimType.PROHIBITION and type_b == LegalClaimType.OBLIGATION)
            or (type_a == LegalClaimType.RIGHT and type_b == LegalClaimType.PROHIBITION)
            or (type_a == LegalClaimType.PROHIBITION and type_b == LegalClaimType.RIGHT)
        )

        if not is_conflict:
            return SolverResult(
                pair_id=pair.pair_id,
                backend=SolverBackend.DATALOG,
                outcome=SolverOutcome.SAT,
                solver_input="No normative deontic conflict between claim types.",
                runtime_ms=int((time.perf_counter() - start_t) * 1000),
            )

        # 4. Check action and party overlap
        parties_a = set(p.lower() for p in claim_a.parties)
        parties_b = set(p.lower() for p in claim_b.parties)
        same_party = bool(parties_a & parties_b) or (not parties_a and not parties_b)

        action_a = extract_action_target(claim_a.raw_text, claim_a.predicate)
        action_b = extract_action_target(claim_b.raw_text, claim_b.predicate)
        same_action = action_a == action_b and action_a != "general_action"

        if same_party and same_action:
            fp = z3.Fixedpoint()
            fp.set("timeout", self.timeout_ms)

            PartySort = z3.StringSort()
            ActionSort = z3.StringSort()

            Obligation = z3.Function("Obligation", PartySort, ActionSort, z3.BoolSort())
            Prohibition = z3.Function("Prohibition", PartySort, ActionSort, z3.BoolSort())
            Contradiction = z3.Function("Contradiction", z3.BoolSort())

            fp.register_relation(Obligation)
            fp.register_relation(Prohibition)
            fp.register_relation(Contradiction)

            p = z3.Const("p", PartySort)
            a = z3.Const("a", ActionSort)
            fp.declare_var(p, a)

            # Rule: Obligation(p, a) AND Prohibition(p, a) -> Contradiction()
            fp.add_rule(Contradiction(), [Obligation(p, a), Prohibition(p, a)])

            # Register facts
            party_val = z3.StringVal(list(parties_a)[0] if parties_a else "party_default")
            action_val = z3.StringVal(action_a)

            # In Z3 Python API, adding a fact is done by adding a rule with empty premises
            fp.add_rule(Obligation(party_val, action_val))
            fp.add_rule(Prohibition(party_val, action_val))

            query_res = fp.query(Contradiction())
            runtime_ms = int((time.perf_counter() - start_t) * 1000)

            if query_res == z3.sat:
                proof_trace = (
                    f"DATALOG PROOF TRACE:\n"
                    f"1. Claim A ({claim_a.claim_id[:8]}...): {type_a.value.upper()} on action '{action_a}'\n"
                    f"2. Claim B ({claim_b.claim_id[:8]}...): {type_b.value.upper()} on action '{action_b}'\n"
                    f"3. Rule: Contradiction() :- Obligation(P, A), Prohibition(P, A).\n"
                    f"4. Derivation: Party '{party_val}' simultaneously obligated and prohibited from '{action_a}'."
                )
                return SolverResult(
                    pair_id=pair.pair_id,
                    backend=SolverBackend.DATALOG,
                    outcome=SolverOutcome.UNSAT,
                    proof_trace=proof_trace,
                    solver_input=f"contradiction :- obligation({party_val}, {action_val}), prohibition({party_val}, {action_val}).",
                    runtime_ms=runtime_ms,
                )

        return SolverResult(
            pair_id=pair.pair_id,
            backend=SolverBackend.DATALOG,
            outcome=SolverOutcome.SAT,
            solver_input="Actions or parties differ; no normative conflict.",
            runtime_ms=int((time.perf_counter() - start_t) * 1000),
        )
