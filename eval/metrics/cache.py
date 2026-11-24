"""
Result caching keyed on (document_hash, system_id, config_hash, seed).
Prevents duplicate LLM invocations and provides hard cost budget guarding.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Optional

from eval.models import EvalSystemOutput


class EvalResultCache:
    """Disk cache for evaluation outputs with a hard budget limit."""

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        hard_cost_limit_usd: float = 5.0,
    ):
        self.cache_dir = cache_dir or Path(".eval_cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.hard_cost_limit_usd = hard_cost_limit_usd
        self.cumulative_cost_usd = 0.0

    @staticmethod
    def make_cache_key(doc_hash: str, system_id: str, config_hash: str, seed: int) -> str:
        key_raw = f"{doc_hash}_{system_id}_{config_hash}_{seed}"
        return hashlib.sha256(key_raw.encode("utf-8")).hexdigest()

    def get(self, cache_key: str) -> Optional[EvalSystemOutput]:
        target = self.cache_dir / f"{cache_key}.json"
        if target.exists():
            try:
                with open(target, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return EvalSystemOutput(**data)
            except Exception:
                return None
        return None

    def put(self, cache_key: str, output: EvalSystemOutput) -> None:
        target = self.cache_dir / f"{cache_key}.json"
        with open(target, "w", encoding="utf-8") as f:
            f.write(output.model_dump_json(indent=2))

    def track_cost_and_check_budget(self, additional_cost_usd: float) -> bool:
        """
        Increment cumulative cost and return True if within budget,
        or False if hard budget limit has been exceeded.
        """
        self.cumulative_cost_usd += additional_cost_usd
        if self.cumulative_cost_usd > self.hard_cost_limit_usd:
            return False
        return True
