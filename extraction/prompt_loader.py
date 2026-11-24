"""
Versioned prompt template loader.
"""
from __future__ import annotations

from pathlib import Path


def get_prompts_dir() -> Path:
    """Return the absolute path to configs/prompts."""
    base_dir = Path(__file__).resolve().parent.parent
    return base_dir / "configs" / "prompts"


def load_prompt(name: str, version: str = "v1", **kwargs: object) -> str:
    """
    Load a versioned prompt template from disk and format with kwargs.

    Args:
        name: Template base name (e.g. 'legal', 'financial', 'defined_terms').
        version: Version identifier (default 'v1').
        **kwargs: Variables to interpolate into the template.

    Returns:
        Formatted prompt string.
    """
    prompt_file = get_prompts_dir() / f"{name}_{version}.txt"
    if not prompt_file.exists():
        raise FileNotFoundError(
            f"Prompt template '{prompt_file}' not found. Check configs/prompts directory."
        )

    template = prompt_file.read_text(encoding="utf-8")
    # Strict formatting
    return template.format(**kwargs)
