"""Answerability evaluation against configurable question ontology."""

from __future__ import annotations

from typing import Any

from aeo_auditor.client_config import ClientConfig
from aeo_auditor.models import LocationEntity, QuestionResult
from aeo_auditor.paths import load_yaml, project_path


def load_questions(path: Any | None = None) -> dict[str, list[dict[str, Any]]]:
    path = path or project_path("config", "questions.yaml")
    data = load_yaml(path)
    return dict(data.get("categories") or {})


def _get_nested(entity: LocationEntity, dotted: str) -> Any:
    parts = dotted.split(".")
    if parts[0] == "hours":
        if len(parts) == 1:
            return entity.hours or None
        return entity.hours.get(parts[1]) if entity.hours else None
    if parts[0] == "address":
        if parts[-1] == "full":
            return entity.address.full
        return getattr(entity.address, parts[1], None) if len(parts) > 1 else entity.address
    if parts[0] == "services":
        return getattr(entity.services, parts[1], None) if len(parts) > 1 else None
    if parts[0] == "amenities":
        return getattr(entity.amenities, parts[1], None) if len(parts) > 1 else None
    if parts[0] == "payment_methods":
        return entity.payment_methods or None
    if parts[0] == "menu_features":
        return entity.menu_features or None
    if parts[0] == "nearby_locations":
        return entity.nearby_locations or None
    if parts[0] == "nearby_landmarks":
        return entity.nearby_landmarks or None
    return None


def _keyword_hit(text: str, keywords: list[str]) -> str | None:
    lower = text.lower()
    for kw in keywords:
        if kw.lower() in lower:
            # return a short evidence window
            idx = lower.find(kw.lower())
            start = max(0, idx - 40)
            end = min(len(text), idx + len(kw) + 40)
            return text[start:end].replace("\n", " ").strip()
    return None


def _faq_hit(entity: LocationEntity, question: str, keywords: list[str]) -> str | None:
    q_lower = question.lower()
    for faq in entity.visible_faqs:
        blob = f"{faq.question} {faq.answer}"
        if any(kw.lower() in blob.lower() for kw in keywords) or any(
            token in faq.question.lower() for token in q_lower.split() if len(token) > 4
        ):
            return f"Q: {faq.question} A: {faq.answer[:180]}"
    return None


def evaluate_questions(
    entity: LocationEntity,
    *,
    client: ClientConfig | None = None,
    questions: dict[str, list[dict[str, Any]]] | None = None,
    visible_text: str = "",
) -> list[QuestionResult]:
    cats = questions or load_questions()
    allowed = set(client.question_sets) if client and client.question_sets else set(cats.keys())
    results: list[QuestionResult] = []
    text = visible_text or entity.local_content.description or ""
    # Prefer full visible text if available via visible_facts marker
    # Callers should pass visible_text from RawPageData

    for category, items in cats.items():
        if category not in allowed:
            continue
        for item in items:
            qid = item["id"]
            question = item["question"]
            fact_keys = list(item.get("fact_keys") or [])
            keywords = list(item.get("keywords") or [])

            fact_value = None
            for key in fact_keys:
                fact_value = _get_nested(entity, key)
                if fact_value not in (None, [], {}, ""):
                    break

            structured = False
            for key in fact_keys:
                # structured presence
                if key.startswith("services.") or key.startswith("amenities."):
                    # services rarely structured unless in schema amenityFeature — keep false unless in structured_facts
                    if key in entity.structured_facts or key.split(".")[-1] in str(entity.structured_facts):
                        structured = True
                if key in ("address.street", "address.city", "address.full") and entity.structured_facts.get("address"):
                    structured = True
                if key.startswith("hours") and entity.structured_facts.get("hours"):
                    structured = True
                if key == "nearby_locations" and entity.nearby_locations:
                    # nearby usually from links = visible
                    pass

            # Hours/address from schema count as structured known
            if fact_keys and any(k.startswith("hours") for k in fact_keys) and entity.structured_facts.get("hours"):
                structured = True
                if fact_value in (None, [], {}, ""):
                    fact_value = entity.structured_facts.get("hours")
            if any(k.startswith("address") for k in fact_keys) and entity.structured_facts.get("address"):
                structured = True
                if fact_value in (None, [], {}, ""):
                    addr = entity.structured_facts["address"]
                    fact_value = addr.get("street") or addr

            visible = False
            evidence = None
            source = None

            if keywords and text:
                hit = _keyword_hit(text, keywords)
                if hit:
                    visible = True
                    evidence = hit
                    source = "visible_content"
                    if fact_value in (None, [], {}, ""):
                        fact_value = True

            faq_evidence = _faq_hit(entity, question, keywords) if keywords else None
            if faq_evidence:
                visible = True
                evidence = evidence or faq_evidence
                source = source or "faq"
                if fact_value in (None, [], {}, ""):
                    fact_value = True

            # Visible facts map
            for key in fact_keys:
                if key in entity.visible_facts or f"hours.{key.split('.')[-1]}" in entity.visible_facts:
                    visible = True
                    evidence = evidence or str(entity.visible_facts.get(key) or entity.visible_facts.get(f"hours.{key.split('.')[-1]}"))
                    source = source or "visible_content"

            if any(k.startswith("address") for k in fact_keys) and entity.address.street:
                if "address" in entity.visible_facts or entity.address.street:
                    # address often from schema; mark visible if street appears in text
                    if entity.address.street and entity.address.street.lower() in text.lower():
                        visible = True
                        evidence = evidence or entity.address.street
                        source = source or "visible_content"
                    fact_value = fact_value or entity.address.full or entity.address.street

            if fact_keys == ["nearby_locations"] and entity.nearby_locations:
                fact_value = [n.url for n in entity.nearby_locations[:3]]
                visible = True
                evidence = evidence or f"{len(entity.nearby_locations)} nearby location links"
                source = source or "visible_content"

            fact_known = fact_value not in (None, [], {}, "")
            # ANSWERABLE: explicit answer with evidence (visible or structured)
            explicitly = bool(fact_known and (visible or structured) and (evidence or structured))
            if structured and fact_known and not evidence:
                evidence = f"Structured: {str(fact_value)[:160]}"
                source = source or "structured_data"
                explicitly = True

            confidence = 0.0
            if explicitly:
                confidence = 0.95 if (visible and structured) else 0.85 if visible else 0.8
            elif fact_known:
                confidence = 0.5

            results.append(
                QuestionResult(
                    question_id=qid,
                    category=category,
                    question=question,
                    fact_known=fact_known,
                    visible_on_page=visible,
                    structured=structured,
                    explicitly_answered=explicitly,
                    confidence=confidence,
                    evidence=evidence,
                    source=source,
                )
            )
    return results
