"""Optional LLM helpers — disabled unless OPENAI_API_KEY is set.

Deterministic path is the default. LLM may only assist with NL matching /
boilerplate classification and must retain evidence. Never invent attributes.
"""

from __future__ import annotations

import os
from typing import Any


def llm_enabled() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def classify_boilerplate(text: str, city: str | None = None) -> dict[str, Any]:
    """Return a heuristic classification; optional LLM hook left unimplemented without key."""
    generic_markers = ["since '92", "positive energy", "broistas", "change the world", "killer coffees"]
    hits = [m for m in generic_markers if m.lower() in text.lower()]
    city_mentioned = bool(city and city.lower() in text.lower())
    result = {
        "is_boilerplate": len(hits) >= 2 and not city_mentioned,
        "markers": hits,
        "city_mentioned": city_mentioned,
        "evidence": text[:240],
        "source": "deterministic_heuristic",
    }
    if llm_enabled():
        # Intentionally not calling external APIs in MVP default path.
        # Hook reserved for future OpenAI-assisted classification with evidence.
        result["llm_available"] = True
    return result


def nl_answers_question(question: str, passage: str) -> dict[str, Any] | None:
    """Optional NL matcher. Returns None when LLM unavailable (caller uses deterministic rules)."""
    if not llm_enabled():
        return None
    return None
