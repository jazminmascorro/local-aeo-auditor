"""Deterministic AEO scoring from config/scoring.yaml."""

from __future__ import annotations

from typing import Any

from aeo_auditor.client_config import ClientConfig
from aeo_auditor.models import (
    CategoryScore,
    EvidenceFinding,
    LocationEntity,
    QuestionResult,
    Scorecard,
)
from aeo_auditor.paths import load_yaml, project_path


def load_scoring_config(path: Any | None = None) -> dict[str, Any]:
    path = path or project_path("config", "scoring.yaml")
    return load_yaml(path)


def _finding_map(entity: LocationEntity) -> dict[str, EvidenceFinding]:
    return {f.check: f for f in entity.findings}


def _pass(finding: EvidenceFinding | None) -> bool:
    return bool(finding and finding.result is True)


def score_discovery(entity: LocationEntity, cfg: dict[str, Any]) -> CategoryScore:
    checks_cfg = cfg["categories"]["discovery"]["checks"]
    fmap = _finding_map(entity)
    earned = 0.0
    details: list[EvidenceFinding] = []
    for check in checks_cfg:
        cid = check["id"]
        points = float(check["points"])
        finding = fmap.get(cid)
        ok = _pass(finding)
        # in_sitemap: if unknown (None), award partial? Plan says evaluate included in sitemap.
        # If None (single-URL mode), give points when status 200 so single-page mode isn't punished harshly —
        # actually plan says don't fabricate. Award 0 when unknown for sitemap.
        if cid == "in_sitemap" and finding and finding.result is None:
            ok = False
        if ok:
            earned += points
        details.append(
            EvidenceFinding(
                check=cid,
                result=ok,
                evidence=finding.evidence if finding else None,
                source=finding.source if finding else None,
            )
        )
    return CategoryScore(name="discovery", score=earned, max_points=float(cfg["categories"]["discovery"]["max_points"]), checks=details)


def score_entity_clarity(entity: LocationEntity, cfg: dict[str, Any]) -> CategoryScore:
    mapping = {
        "location_name": bool(entity.location_name),
        "address_street": bool(entity.address.street),
        "address_city_region_postal": bool(
            entity.address.city and entity.address.region and entity.address.postal_code
        ),
        "phone": bool(entity.phone),
        "geo_coordinates": entity.geo.latitude is not None and entity.geo.longitude is not None,
        "location_identifier": bool(entity.location_id),
        "breadcrumbs": bool(entity.breadcrumbs),
        "nearby_locations": bool(entity.nearby_locations),
    }
    earned = 0.0
    details: list[EvidenceFinding] = []
    for check in cfg["categories"]["entity_clarity"]["checks"]:
        cid = check["id"]
        points = float(check["points"])
        ok = bool(mapping.get(cid))
        if ok:
            earned += points
        evidence = None
        if cid == "location_name":
            evidence = entity.location_name
        elif cid == "address_street":
            evidence = entity.address.street
        elif cid == "phone":
            evidence = entity.phone
        elif cid == "geo_coordinates":
            evidence = f"{entity.geo.latitude},{entity.geo.longitude}" if ok else None
        elif cid == "location_identifier":
            evidence = entity.location_id
        details.append(EvidenceFinding(check=cid, result=ok, evidence=evidence, source="entity"))
    return CategoryScore(
        name="entity_clarity",
        score=earned,
        max_points=float(cfg["categories"]["entity_clarity"]["max_points"]),
        checks=details,
    )


def score_structured_data(entity: LocationEntity, cfg: dict[str, Any], client: ClientConfig | None) -> CategoryScore:
    valid_json = any(e.valid and e.types for e in entity.schema_entities)
    expected = set(client.expected_schema_types) if client and client.expected_schema_types else {
        "LocalBusiness",
        "Restaurant",
        "CafeOrCoffeeShop",
        "FoodEstablishment",
        "Store",
    }
    business_type_ok = any(t in expected or t == "LocalBusiness" for t in entity.schema_types)
    location_specific = bool(
        entity.structured_facts.get("address")
        or entity.structured_facts.get("location_id")
        or entity.structured_facts.get("geo")
    )
    s_addr = bool((entity.structured_facts.get("address") or {}).get("street"))
    s_phone = bool(entity.structured_facts.get("phone"))
    s_geo = bool(entity.structured_facts.get("geo") and (
        (entity.structured_facts["geo"] or {}).get("latitude") is not None
    ))
    s_hours = bool(entity.structured_facts.get("hours"))
    parent = bool(entity.structured_facts.get("parent_organization") or entity.structured_facts.get("name"))
    # URL alignment: absolute preferred; relative schema URL is weak
    schema_url = entity.structured_facts.get("url")
    canon_ok = False
    if schema_url and entity.canonical_url:
        canon_ok = str(schema_url).rstrip("/") in entity.canonical_url or entity.canonical_url.rstrip("/").endswith(
            str(schema_url).lstrip("/").rstrip("/")
        )
    elif schema_url and entity.url:
        canon_ok = str(schema_url) in entity.url or entity.url.endswith(str(schema_url).lstrip("/"))

    mapping = {
        "valid_json_ld": valid_json,
        "business_entity_type": business_type_ok,
        "location_specific_schema": location_specific,
        "schema_address": s_addr,
        "schema_phone": s_phone,
        "schema_geo": s_geo,
        "schema_hours": s_hours,
        "parent_organization": parent,
        "canonical_url_alignment": canon_ok,
    }
    earned = 0.0
    details: list[EvidenceFinding] = []
    for check in cfg["categories"]["structured_data"]["checks"]:
        cid = check["id"]
        points = float(check["points"])
        ok = bool(mapping.get(cid))
        if ok:
            earned += points
        details.append(
            EvidenceFinding(
                check=cid,
                result=ok,
                evidence=", ".join(entity.schema_types) if cid == "business_entity_type" else str(mapping.get(cid)),
                source="structured_data",
            )
        )
    return CategoryScore(
        name="structured_data",
        score=earned,
        max_points=float(cfg["categories"]["structured_data"]["max_points"]),
        checks=details,
    )


def score_answer_coverage(results: list[QuestionResult], cfg: dict[str, Any]) -> CategoryScore:
    max_points = float(cfg["categories"]["answer_coverage"]["max_points"])
    relevant = len(results) or 1
    answerable = sum(1 for r in results if r.explicitly_answered)
    pct = answerable / relevant
    score = round(pct * max_points, 2)
    return CategoryScore(
        name="answer_coverage",
        score=score,
        max_points=max_points,
        checks=[
            EvidenceFinding(
                check="answerable_ratio",
                result=pct,
                evidence=f"{answerable} / {relevant} answerable",
                source="answers",
            )
        ],
    )


def score_local_uniqueness(entity: LocationEntity, cfg: dict[str, Any], peer_boilerplate: str | None = None) -> CategoryScore:
    desc = entity.local_content.description or ""
    city = (entity.address.city or "").lower()
    has_loc_desc = bool(desc and city and city in desc.lower() and len(desc) > 40)
    # neighborhood / unique content: word count + city mention beyond brand boilerplate
    generic_markers = ["since '92", "positive energy", "broistas", "change the world"]
    boilerplate_hits = sum(1 for m in generic_markers if m.lower() in (desc + " " + (entity.meta_description or "")).lower())
    unique_neighborhood = has_loc_desc and boilerplate_hits < 2 and entity.local_content.word_count > 150
    amenities_ok = any(v is True for v in entity.amenities.model_dump().values())
    services_ok = any(v is True for v in entity.services.model_dump().values())
    local_faqs = bool(entity.visible_faqs)
    landmarks = bool(entity.nearby_landmarks)
    limited_boilerplate = boilerplate_hits <= 1 or entity.local_content.word_count > 400

    mapping = {
        "location_description": has_loc_desc,
        "unique_neighborhood_content": unique_neighborhood,
        "location_amenities": amenities_ok,
        "location_services": services_ok,
        "local_faqs": local_faqs,
        "nearby_landmarks": landmarks,
        "limited_boilerplate": limited_boilerplate,
    }
    earned = 0.0
    details: list[EvidenceFinding] = []
    for check in cfg["categories"]["local_uniqueness"]["checks"]:
        cid = check["id"]
        points = float(check["points"])
        ok = bool(mapping.get(cid))
        if ok:
            earned += points
        details.append(
            EvidenceFinding(
                check=cid,
                result=ok,
                evidence=f"word_count={entity.local_content.word_count}" if "unique" in cid or cid == "limited_boilerplate" else None,
                source="local_content",
            )
        )
    return CategoryScore(
        name="local_uniqueness",
        score=earned,
        max_points=float(cfg["categories"]["local_uniqueness"]["max_points"]),
        checks=details,
    )


def band_for_score(total: float, cfg: dict[str, Any]) -> str:
    bands = sorted(cfg.get("bands") or [], key=lambda b: b["min"], reverse=True)
    for band in bands:
        if total >= float(band["min"]):
            return str(band["label"])
    return "Weak"


def score_location(
    entity: LocationEntity,
    question_results: list[QuestionResult],
    *,
    client: ClientConfig | None = None,
    scoring_cfg: dict[str, Any] | None = None,
) -> Scorecard:
    cfg = scoring_cfg or load_scoring_config()
    discovery = score_discovery(entity, cfg)
    entity_clarity = score_entity_clarity(entity, cfg)
    structured = score_structured_data(entity, cfg, client)
    answers = score_answer_coverage(question_results, cfg)
    uniqueness = score_local_uniqueness(entity, cfg)
    total = round(
        discovery.score + entity_clarity.score + structured.score + answers.score + uniqueness.score,
        2,
    )
    return Scorecard(
        total=total,
        max_total=float(cfg.get("max_total", 100)),
        discovery=discovery,
        entity_clarity=entity_clarity,
        structured_data=structured,
        answer_coverage=answers,
        local_uniqueness=uniqueness,
        band=band_for_score(total, cfg),
    )
