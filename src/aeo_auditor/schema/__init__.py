"""JSON-LD schema extraction and audit helpers."""

from __future__ import annotations

from typing import Any

from aeo_auditor.models import SchemaEntity

BUSINESS_TYPES = {
    "LocalBusiness",
    "Restaurant",
    "CafeOrCoffeeShop",
    "FoodEstablishment",
    "Store",
    "Organization",
    "Place",
}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _types_of(obj: dict[str, Any]) -> list[str]:
    raw = obj.get("@type")
    types = []
    for t in _as_list(raw):
        if isinstance(t, str):
            types.append(t.split("/")[-1])
    return types


def flatten_json_ld(blocks: list[Any]) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        if "@graph" in node:
            walk(node["@graph"])
            # still keep top-level if it has @type
        if "@type" in node:
            entities.append(node)
        # nested common containers
        for key in ("mainEntity", "mainEntityOfPage", "itemListElement", "department", "branch"):
            if key in node:
                walk(node[key])

    for block in blocks:
        walk(block)
    return entities


def extract_schema_entities(blocks: list[Any], errors: list[str] | None = None) -> list[SchemaEntity]:
    entities: list[SchemaEntity] = []
    for obj in flatten_json_ld(blocks):
        entities.append(SchemaEntity(types=_types_of(obj), raw=obj, valid=True))
    for err in errors or []:
        entities.append(SchemaEntity(types=[], raw={}, valid=False, parse_error=err))
    return entities


def first_business_entity(entities: list[SchemaEntity]) -> SchemaEntity | None:
    for ent in entities:
        if any(t in BUSINESS_TYPES for t in ent.types):
            # Prefer LocalBusiness / Cafe over bare Organization
            if any(t in {"LocalBusiness", "CafeOrCoffeeShop", "Restaurant", "FoodEstablishment", "Store"} for t in ent.types):
                return ent
    for ent in entities:
        if any(t in BUSINESS_TYPES for t in ent.types):
            return ent
    return None


def schema_address(raw: dict[str, Any]) -> dict[str, str | None]:
    addr = raw.get("address")
    if isinstance(addr, list) and addr:
        addr = addr[0]
    if not isinstance(addr, dict):
        return {}
    return {
        "street": addr.get("streetAddress"),
        "city": addr.get("addressLocality"),
        "region": addr.get("addressRegion"),
        "postal_code": addr.get("postalCode"),
        "country": addr.get("addressCountry")
        if isinstance(addr.get("addressCountry"), str)
        else (addr.get("addressCountry") or {}).get("name")
        if isinstance(addr.get("addressCountry"), dict)
        else None,
    }


def schema_geo(raw: dict[str, Any]) -> dict[str, float | None]:
    lat = raw.get("latitude")
    lng = raw.get("longitude")
    geo = raw.get("geo")
    if isinstance(geo, dict):
        lat = lat if lat is not None else geo.get("latitude")
        lng = lng if lng is not None else geo.get("longitude")
    try:
        lat_f = float(lat) if lat is not None else None
    except (TypeError, ValueError):
        lat_f = None
    try:
        lng_f = float(lng) if lng is not None else None
    except (TypeError, ValueError):
        lng_f = None
    return {"latitude": lat_f, "longitude": lng_f}


def schema_hours(raw: dict[str, Any]) -> dict[str, Any]:
    hours: dict[str, Any] = {}
    oh = raw.get("openingHours")
    if oh:
        hours["openingHours"] = oh if isinstance(oh, list) else [oh]
    specs = raw.get("openingHoursSpecification")
    if specs:
        hours["openingHoursSpecification"] = specs if isinstance(specs, list) else [specs]
    return hours


def schema_phone(raw: dict[str, Any]) -> str | None:
    phone = raw.get("telephone") or raw.get("phone")
    if isinstance(phone, list) and phone:
        phone = phone[0]
    return str(phone) if phone else None


def collect_schema_types(entities: list[SchemaEntity]) -> list[str]:
    seen: list[str] = []
    for ent in entities:
        for t in ent.types:
            if t not in seen:
                seen.append(t)
    return seen
