"""
Synthetic contradiction injection engine.
Generates single, planted contradictions or hard negatives in clean documents
and outputs exact ground-truth character offsets.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional, Tuple
from schemas.finding import FindingStatus
from schemas.span import SourceSpan
from eval.models import (
    GroundTruthAnnotation,
    InjectedDocument,
    InjectionCategory,
    InjectionType,
)


class ContradictionInjector:
    """
    Deterministically plants contradictions or hard negatives into documents,
    recomputing exact character offsets and verifying the span offset invariant:
    full_text[char_start:char_end] == text_snippet.
    """

    def __init__(self, seed: int = 42):
        self.seed = seed

    @staticmethod
    def _compute_doc_id(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _replace_and_reoffset(
        self,
        full_text: str,
        target_str: str,
        replacement_str: str,
        start_hint: int = 0,
    ) -> Tuple[str, int, int]:
        """Replace target_str starting around start_hint and return (new_text, new_start, new_end)."""
        idx = full_text.find(target_str, start_hint)
        if idx == -1:
            idx = full_text.find(target_str)
        if idx == -1:
            raise ValueError(f"Target string '{target_str}' not found in document text.")

        new_text = full_text[:idx] + replacement_str + full_text[idx + len(target_str):]
        new_start = idx
        new_end = idx + len(replacement_str)
        return new_text, new_start, new_end

    def inject_legal_deadline(
        self,
        full_text: str,
        base_clause: str,
        target_clause: str,
        new_days: int = 15,
        title: str = "Contract",
    ) -> InjectedDocument:
        """Mutate a deadline in target_clause to conflict with base_clause."""
        # Find numeric day pattern in target_clause (e.g., "30 days", "thirty (30) days", "(60) days")
        pattern = r"(?:(?:\w+)\s*)?(?:\([^\)]+\)\s*|\b)(\d+)\s*(?:\([^\)]+\)\s*)?days?"
        match = re.search(pattern, target_clause, re.IGNORECASE)
        if not match:
            # Fallback to word-number patterns e.g. thirty days
            pattern = r"\b(?:thirty|sixty|ninety|forty-five|forty|twenty|fifteen|ten)\b\s*(?:\([^\)]+\)\s*)?days?"
            match = re.search(pattern, target_clause, re.IGNORECASE)
            if not match:
                raise ValueError(f"No day pattern found in target clause: '{target_clause}'")

        replacement_str = re.sub(pattern, f"{new_days} days", target_clause, count=1, flags=re.IGNORECASE)

        # Mutate document text
        new_text, start_mut, end_mut = self._replace_and_reoffset(full_text, target_clause, replacement_str)
        new_doc_id = self._compute_doc_id(new_text)

        # Locate base clause span in new_text
        start_base = new_text.find(base_clause)
        if start_base == -1:
            raise ValueError(f"Base clause '{base_clause}' not found in modified text.")
        end_base = start_base + len(base_clause)

        span_a = SourceSpan(
            doc_id=new_doc_id,
            doc_path="contract.txt",
            char_start=start_base,
            char_end=end_base,
            text_snippet=new_text[start_base:end_base],
        )
        span_b = SourceSpan(
            doc_id=new_doc_id,
            doc_path="contract.txt",
            char_start=start_mut,
            char_end=end_mut,
            text_snippet=new_text[start_mut:end_mut],
        )

        annotation = GroundTruthAnnotation(
            injection_id=f"inj_deadline_{self.seed}",
            doc_id=new_doc_id,
            category=InjectionCategory.LEGAL,
            injection_type=InjectionType.DEADLINE_ALTERATION,
            expected_verdict=FindingStatus.CONTRADICTION,
            original_span_a=span_a,
            original_span_b=span_b,
            modified_span=span_b,
            mutation_description=f"Altered deadline to {new_days} days creating UNSAT conflict with base clause.",
            seed=self.seed,
            expected_unsat_core=["c1", "c2"],
        )

        return InjectedDocument(
            doc_id=new_doc_id,
            title=title,
            full_text=new_text,
            annotations=[annotation],
        )

    def inject_legal_deontic(
        self,
        full_text: str,
        base_obligation_clause: str,
        target_clause: str,
        title: str = "Contract",
    ) -> InjectedDocument:
        """Flip 'shall' to 'shall not' in target_clause on the same party and action."""
        if "shall not" in target_clause:
            mutated_clause = target_clause.replace("shall not", "shall")
        elif "shall" in target_clause:
            mutated_clause = target_clause.replace("shall", "shall not")
        else:
            raise ValueError(f"No 'shall' keyword found in target clause: '{target_clause}'")

        new_text, start_mut, end_mut = self._replace_and_reoffset(full_text, target_clause, mutated_clause)
        new_doc_id = self._compute_doc_id(new_text)

        start_base = new_text.find(base_obligation_clause)
        if start_base == -1:
            raise ValueError(f"Base clause not found in mutated text.")
        end_base = start_base + len(base_obligation_clause)

        span_a = SourceSpan(
            doc_id=new_doc_id,
            doc_path="contract.txt",
            char_start=start_base,
            char_end=end_base,
            text_snippet=new_text[start_base:end_base],
        )
        span_b = SourceSpan(
            doc_id=new_doc_id,
            doc_path="contract.txt",
            char_start=start_mut,
            char_end=end_mut,
            text_snippet=new_text[start_mut:end_mut],
        )

        annotation = GroundTruthAnnotation(
            injection_id=f"inj_deontic_{self.seed}",
            doc_id=new_doc_id,
            category=InjectionCategory.LEGAL,
            injection_type=InjectionType.OBLIGATION_TO_PROHIBITION,
            expected_verdict=FindingStatus.CONTRADICTION,
            original_span_a=span_a,
            original_span_b=span_b,
            modified_span=span_b,
            mutation_description="Flipped deontic modality from obligation to prohibition on identical action.",
            seed=self.seed,
            expected_unsat_core=["c1", "c2"],
        )

        return InjectedDocument(
            doc_id=new_doc_id,
            title=title,
            full_text=new_text,
            annotations=[annotation],
        )

    def inject_financial_narrative_growth(
        self,
        full_text: str,
        table_snippet: str,
        narrative_snippet: str,
        corrupted_pct: str = "25.0%",
        title: str = "Filing",
    ) -> InjectedDocument:
        """Mutate narrative growth rate to contradict table-derived growth rate."""
        pattern = r"(\d+(?:\.\d+)?)\s*%"
        mutated_narrative = re.sub(pattern, corrupted_pct, narrative_snippet, count=1)
        if mutated_narrative == narrative_snippet:
            mutated_narrative = f"{narrative_snippet} reflecting {corrupted_pct} growth"

        new_text, start_mut, end_mut = self._replace_and_reoffset(full_text, narrative_snippet, mutated_narrative)
        new_doc_id = self._compute_doc_id(new_text)

        start_table = new_text.find(table_snippet)
        if start_table == -1:
            raise ValueError(f"Table snippet not found in mutated text.")
        end_table = start_table + len(table_snippet)

        span_a = SourceSpan(
            doc_id=new_doc_id,
            doc_path="filing.txt",
            char_start=start_table,
            char_end=end_table,
            text_snippet=new_text[start_table:end_table],
        )
        span_b = SourceSpan(
            doc_id=new_doc_id,
            doc_path="filing.txt",
            char_start=start_mut,
            char_end=end_mut,
            text_snippet=new_text[start_mut:end_mut],
        )

        annotation = GroundTruthAnnotation(
            injection_id=f"inj_fin_growth_{self.seed}",
            doc_id=new_doc_id,
            category=InjectionCategory.FINANCIAL,
            injection_type=InjectionType.GROWTH_RATE_DISPARITY,
            expected_verdict=FindingStatus.CONTRADICTION,
            original_span_a=span_a,
            original_span_b=span_b,
            modified_span=span_b,
            mutation_description=f"Corrupted narrative growth percentage to {corrupted_pct}.",
            seed=self.seed,
            expected_unsat_core=["c1", "c2"],
        )

        return InjectedDocument(
            doc_id=new_doc_id,
            title=title,
            full_text=new_text,
            annotations=[annotation],
        )

    def inject_hard_negative_rounding(
        self,
        full_text: str,
        table_snippet: str,
        narrative_snippet: str,
        within_tolerance_pct: str = "12.4%",
        title: str = "Filing",
    ) -> InjectedDocument:
        """Mutate percentage within 0.1% rounding tolerance (must NOT be flagged as CONTRADICTION)."""
        pattern = r"(\d+(?:\.\d+)?)\s*%"
        mutated_narrative = re.sub(pattern, within_tolerance_pct, narrative_snippet, count=1)
        new_text, start_mut, end_mut = self._replace_and_reoffset(full_text, narrative_snippet, mutated_narrative)
        new_doc_id = self._compute_doc_id(new_text)

        start_table = new_text.find(table_snippet)
        end_table = start_table + len(table_snippet)

        span_a = SourceSpan(
            doc_id=new_doc_id,
            doc_path="filing.txt",
            char_start=start_table,
            char_end=end_table,
            text_snippet=new_text[start_table:end_table],
        )
        span_b = SourceSpan(
            doc_id=new_doc_id,
            doc_path="filing.txt",
            char_start=start_mut,
            char_end=end_mut,
            text_snippet=new_text[start_mut:end_mut],
        )

        annotation = GroundTruthAnnotation(
            injection_id=f"inj_hn_round_{self.seed}",
            doc_id=new_doc_id,
            category=InjectionCategory.HARD_NEGATIVE,
            injection_type=InjectionType.ROUNDING_WITHIN_TOLERANCE,
            expected_verdict=FindingStatus.CONSISTENT,
            original_span_a=span_a,
            original_span_b=span_b,
            modified_span=span_b,
            mutation_description="Mutated percentage within explicit 0.1% rounding tolerance. Should be CONSISTENT.",
            seed=self.seed,
        )

        return InjectedDocument(
            doc_id=new_doc_id,
            title=title,
            full_text=new_text,
            annotations=[annotation],
        )

    def create_clean_document(
        self,
        full_text: str,
        title: str = "Clean Document",
    ) -> InjectedDocument:
        """Creates a clean document wrapper with no injection (used for False Positive evaluation)."""
        doc_id = self._compute_doc_id(full_text)
        span_clean = SourceSpan(
            doc_id=doc_id,
            doc_path="clean.txt",
            char_start=0,
            char_end=min(len(full_text), 100),
            text_snippet=full_text[:min(len(full_text), 100)],
        )
        annotation = GroundTruthAnnotation(
            injection_id=f"clean_{doc_id[:8]}",
            doc_id=doc_id,
            category=InjectionCategory.CLEAN,
            injection_type=InjectionType.NONE,
            expected_verdict=FindingStatus.CONSISTENT,
            original_span_a=span_clean,
            original_span_b=span_clean,
            mutation_description="Clean document with no synthetic contradiction.",
            seed=self.seed,
        )
        return InjectedDocument(
            doc_id=doc_id,
            title=title,
            full_text=full_text,
            annotations=[annotation],
        )
