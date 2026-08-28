"""Evidence-backed recommendations with priority levels."""

from __future__ import annotations

from aeo_auditor.models import (
    ConflictStatus,
    LocationEntity,
    Priority,
    QuestionResult,
    Recommendation,
)


def generate_recommendations(
    entity: LocationEntity,
    question_results: list[QuestionResult],
) -> tuple[list[Recommendation], list[str], list[str], list[str], list[str]]:
    recs: list[Recommendation] = []
    strengths: list[str] = []
    opportunities: list[str] = []
    missing_answers: list[str] = []
    schema_opportunities: list[str] = []

    if entity.address.street:
        strengths.append("Address clearly exposed")
    if entity.hours:
        strengths.append("Hours information available")
    if entity.breadcrumbs:
        strengths.append("Breadcrumb relationships present")
    if entity.geo.latitude is not None:
        strengths.append("Geo information available")
    if entity.nearby_locations:
        strengths.append("Nearby stores linked")
    if entity.schema_types:
        strengths.append(f"Schema types present: {', '.join(entity.schema_types[:4])}")

    # Conflicts → HIGH
    for conflict in entity.conflicts:
        if conflict.status == ConflictStatus.CONFLICT:
            recs.append(
                Recommendation(
                    priority=Priority.HIGH,
                    title=f"Resolve {conflict.attribute} conflict",
                    message=f"Visible and structured values disagree for {conflict.attribute}.",
                    related_checks=[conflict.attribute],
                    evidence=conflict.evidence,
                )
            )

    # Missing answers
    for qr in question_results:
        if not qr.explicitly_answered:
            missing_answers.append(qr.question)
            if qr.fact_known and not qr.visible_on_page:
                recs.append(
                    Recommendation(
                        priority=Priority.HIGH,
                        title=f"Expose answer: {qr.question}",
                        message="Fact appears known but is not explicitly exposed in visible page content.",
                        related_checks=[qr.question_id],
                        evidence=qr.evidence,
                    )
                )
            elif qr.visible_on_page and not qr.structured:
                recs.append(
                    Recommendation(
                        priority=Priority.MEDIUM,
                        title=f"Structure answer: {qr.question}",
                        message="Fact is visible but not present in machine-readable structured data.",
                        related_checks=[qr.question_id],
                        evidence=qr.evidence,
                    )
                )
            else:
                # only add LOW for high-value categories
                if qr.category in {"services", "amenities", "hours", "location"}:
                    recs.append(
                        Recommendation(
                            priority=Priority.LOW,
                            title=f"Add explicit answer: {qr.question}",
                            message="No explicit evidence found on the page or in structured data.",
                            related_checks=[qr.question_id],
                            evidence=None,
                        )
                    )

    # Schema opportunities
    if not entity.schema_entities or not any(e.valid and e.types for e in entity.schema_entities):
        schema_opportunities.append("No valid JSON-LD business entity detected")
        recs.append(
            Recommendation(
                priority=Priority.HIGH,
                title="Add location LocalBusiness JSON-LD",
                message="Machine-readable location entity missing or invalid.",
                related_checks=["valid_json_ld"],
            )
        )
    else:
        if not (entity.structured_facts.get("address") or {}).get("street"):
            schema_opportunities.append("Structured address incomplete")
        else:
            schema_opportunities.append("Address structured correctly")
        if not entity.structured_facts.get("hours"):
            schema_opportunities.append("Opening hours missing from schema")
        elif not entity.hours.get("by_day"):
            schema_opportunities.append("Opening hours present but may be incomplete")
        if not any(entity.services.model_dump().values()):
            schema_opportunities.append("Service attributes not machine-readable")
        schema_url = entity.structured_facts.get("url")
        if schema_url and isinstance(schema_url, str) and not schema_url.startswith("http"):
            schema_opportunities.append("Schema URL is relative; prefer absolute canonical URL")
            recs.append(
                Recommendation(
                    priority=Priority.MEDIUM,
                    title="Use absolute URLs in schema",
                    message="Schema url fields should align with the absolute canonical URL.",
                    related_checks=["canonical_url_alignment"],
                    evidence=str(schema_url),
                )
            )

    if entity.local_content.word_count < 200:
        opportunities.append("Limited unique location information")
    if entity.visible_faqs and all("dutch" in (f.question + f.answer).lower() for f in entity.visible_faqs[:5]):
        opportunities.append("Generic FAQs may dominate local page")
    if not any(v is True for v in entity.amenities.model_dump().values()):
        opportunities.append("Location amenities unclear")
    if not any(v is True for v in entity.services.model_dump().values()):
        opportunities.append("Location service attributes unclear")

    # Deduplicate recommendations by title
    seen: set[str] = set()
    uniq: list[Recommendation] = []
    # Prefer HIGH then MEDIUM then LOW; cap volume
    for priority in (Priority.HIGH, Priority.MEDIUM, Priority.LOW):
        for rec in recs:
            if rec.priority != priority:
                continue
            if rec.title in seen:
                continue
            seen.add(rec.title)
            uniq.append(rec)
            if len(uniq) >= 40:
                break
        if len(uniq) >= 40:
            break

    return uniq, strengths, opportunities, missing_answers, schema_opportunities
