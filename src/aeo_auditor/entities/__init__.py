"""Normalize raw page + schema into LocationEntity; consistency checks."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

from aeo_auditor.client_config import ClientConfig
from aeo_auditor.models import (
    Address,
    Amenities,
    Conflict,
    ConflictStatus,
    EvidenceFinding,
    Geo,
    LocalContent,
    LocationEntity,
    NearbyLocation,
    Services,
)
from aeo_auditor.models import RawPageData
from aeo_auditor.schema import (
    collect_schema_types,
    extract_schema_entities,
    first_business_entity,
    schema_address,
    schema_geo,
    schema_hours,
    schema_phone,
)

STREET_ABBREV = {
    "east": "e",
    "west": "w",
    "north": "n",
    "south": "s",
    "street": "st",
    "avenue": "ave",
    "road": "rd",
    "boulevard": "blvd",
    "drive": "dr",
    "lane": "ln",
    "court": "ct",
    "parkway": "pkwy",
    "highway": "hwy",
}


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    text = value.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    parts = []
    for token in text.split():
        parts.append(STREET_ABBREV.get(token, token))
    return " ".join(parts)


def normalize_phone(value: str | None) -> str:
    if not value:
        return ""
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def phones_match(a: str | None, b: str | None) -> bool:
    na, nb = normalize_phone(a), normalize_phone(b)
    return bool(na and nb and na == nb)


def addresses_match(a: str | None, b: str | None) -> bool:
    return bool(a and b and normalize_text(a) == normalize_text(b))


def detect_bool_from_text(text: str, keywords: list[str]) -> bool | None:
    lower = text.lower()
    for kw in keywords:
        if kw.lower() in lower:
            return True
    return None


def extract_phone_from_text(text: str) -> str | None:
    patterns = [
        r"\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}",
        r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(0)
    return None


def extract_visible_address(text: str) -> Address:
    # Heuristic: "Street City, ST 12345"
    m = re.search(
        r"(\d{1,6}\s+[A-Za-z0-9 .'-]+?)\s*\n?\s*([A-Za-z .'-]+)\s*,\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)",
        text,
    )
    if not m:
        m = re.search(
            r"(\d{1,6}\s+[A-Za-z0-9 .'-]+)\s+([A-Za-z .'-]+),\s*([A-Z]{2})\s+(\d{5})",
            text,
        )
    if m:
        return Address(
            street=m.group(1).strip(" ,"),
            city=m.group(2).strip(),
            region=m.group(3).strip(),
            postal_code=m.group(4).strip(),
            country="US",
        )
    return Address()


def parse_opening_hours_list(values: list[Any]) -> dict[str, Any]:
    hours: dict[str, Any] = {"raw": values, "by_day": {}}
    day_map = {
        "mo": "monday",
        "tu": "tuesday",
        "we": "wednesday",
        "th": "thursday",
        "fr": "friday",
        "sa": "saturday",
        "su": "sunday",
        "monday": "monday",
        "tuesday": "tuesday",
        "wednesday": "wednesday",
        "thursday": "thursday",
        "friday": "friday",
        "saturday": "saturday",
        "sunday": "sunday",
    }
    for item in values:
        if not isinstance(item, str):
            continue
        m = re.match(r"([A-Za-z]{2,9})\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", item.strip())
        if m:
            day = day_map.get(m.group(1).lower())
            if day:
                hours["by_day"][day] = {"open": m.group(2), "close": m.group(3)}
    if hours["by_day"]:
        # representative open/close if uniform
        opens = {v["open"] for v in hours["by_day"].values()}
        closes = {v["close"] for v in hours["by_day"].values()}
        if len(opens) == 1:
            hours["open"] = next(iter(opens))
        if len(closes) == 1:
            hours["close"] = next(iter(closes))
        if "sunday" in hours["by_day"]:
            hours["sunday"] = hours["by_day"]["sunday"]
    return hours


def is_indexable(robots_meta: str | None) -> bool:
    if not robots_meta:
        return True
    return "noindex" not in robots_meta.lower()


def self_referencing_canonical(url: str, canonical: str | None, final_url: str | None) -> bool | None:
    if not canonical:
        return None
    base = final_url or url

    def norm(u: str) -> str:
        p = urlparse(u)
        path = p.path.rstrip("/") or "/"
        host = (p.hostname or "").lower().removeprefix("www.")
        return f"{host}{path}".lower()

    return norm(urljoin(base, canonical)) == norm(base)


class LocationNormalizer:
    def __init__(self, client: ClientConfig | None = None) -> None:
        self.client = client

    def normalize(
        self,
        raw: RawPageData,
        *,
        in_sitemap: bool | None = None,
    ) -> LocationEntity:
        client_name = self.client.client_name if self.client else ""
        schema_entities = extract_schema_entities(raw.json_ld_blocks, raw.json_ld_errors)
        business = first_business_entity(schema_entities)
        structured: dict[str, Any] = {}
        visible: dict[str, Any] = {}

        addr_vis = extract_visible_address(raw.visible_text)
        phone_vis = extract_phone_from_text(raw.visible_text)
        if addr_vis.street:
            visible["address"] = addr_vis.model_dump()
        if phone_vis:
            visible["phone"] = phone_vis

        hints = (self.client.extraction_hints if self.client else {}) or {}
        service_labels = hints.get("service_labels") or []
        text_lower = raw.visible_text.lower()

        services = Services(
            drive_thru=detect_bool_from_text(
                raw.visible_text, ["drive-thru", "drive thru", "drivethru"] + [s for s in service_labels if "drive" in s]
            ),
            walk_up=detect_bool_from_text(raw.visible_text, ["walk-up", "walk up", "walkup"]),
            pickup=detect_bool_from_text(raw.visible_text, ["pickup", "pick-up", "pick up", "pickup window"]),
            delivery=detect_bool_from_text(raw.visible_text, ["delivery"]),
            order_ahead=detect_bool_from_text(raw.visible_text, ["order ahead", "order-ahead", "order online"]),
        )
        for field, val in services.model_dump().items():
            if val is not None:
                visible[f"services.{field}"] = val

        amenities = Amenities(
            parking=detect_bool_from_text(raw.visible_text, ["parking"]),
            wifi=detect_bool_from_text(raw.visible_text, ["wi-fi", "wifi"]),
            indoor_seating=detect_bool_from_text(raw.visible_text, ["indoor seating"]),
            outdoor_seating=detect_bool_from_text(raw.visible_text, ["outdoor seating", "patio"]),
            wheelchair_accessible=detect_bool_from_text(
                raw.visible_text, ["wheelchair", "wheelchair accessible", "ada accessible"]
            ),
        )
        for field, val in amenities.model_dump().items():
            if val is not None:
                visible[f"amenities.{field}"] = val

        address = Address()
        geo = Geo()
        phone = phone_vis
        hours: dict[str, Any] = {}
        location_id = None
        location_name = raw.h1[0] if raw.h1 else (raw.title.split("|")[0].strip() if raw.title else None)

        if business:
            raw_biz = business.raw
            s_addr = schema_address(raw_biz)
            structured["address"] = s_addr
            address = Address(
                street=s_addr.get("street") or addr_vis.street,
                city=s_addr.get("city") or addr_vis.city,
                region=s_addr.get("region") or addr_vis.region,
                postal_code=s_addr.get("postal_code") or addr_vis.postal_code,
                country=s_addr.get("country") or addr_vis.country or "US",
            )
            s_geo = schema_geo(raw_biz)
            structured["geo"] = s_geo
            geo = Geo(latitude=s_geo.get("latitude"), longitude=s_geo.get("longitude"))
            s_phone = schema_phone(raw_biz)
            if s_phone:
                structured["phone"] = s_phone
                phone = phone or s_phone
            s_hours = schema_hours(raw_biz)
            if s_hours:
                structured["hours"] = s_hours
                if "openingHours" in s_hours:
                    hours = parse_opening_hours_list(list(s_hours["openingHours"]))
                else:
                    hours = s_hours
            if raw_biz.get("name"):
                structured["name"] = raw_biz.get("name")
                location_name = location_name or str(raw_biz.get("name"))
            # identifier from WebPage or business
            for ent in schema_entities:
                if ent.raw.get("identifier"):
                    location_id = str(ent.raw["identifier"])
                    structured["location_id"] = location_id
                    break
            if raw_biz.get("url"):
                structured["url"] = raw_biz.get("url")
            brand = raw_biz.get("brand") or raw_biz.get("parentOrganization")
            if brand:
                structured["parent_organization"] = brand
        else:
            address = addr_vis

        # Prefer visible street if schema missing
        if not address.street and addr_vis.street:
            address = addr_vis

        # Nearby locations from same-host location links
        nearby: list[NearbyLocation] = []
        pattern = self.client.location_url_pattern if self.client else "/locations/"
        page_path = urlparse(raw.final_url or raw.url).path
        for link in raw.links:
            href = link.get("href", "")
            if pattern in href and href.rstrip("/") != (raw.final_url or raw.url).rstrip("/"):
                # same city depth peers
                if href.count("/") >= 5 and link.get("text"):
                    nearby.append(NearbyLocation(name=link.get("text"), url=href))
        # dedupe
        seen_urls: set[str] = set()
        uniq_nearby: list[NearbyLocation] = []
        for n in nearby:
            if n.url and n.url not in seen_urls:
                seen_urls.add(n.url)
                uniq_nearby.append(n)
        nearby = uniq_nearby[:20]

        # Visible hours cues
        if re.search(r"\b\d{1,2}:\d{2}\s*(AM|PM|am|pm)\b", raw.visible_text):
            visible["hours_mention"] = True
            m_open = re.search(r"opens?\s+at\s+(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)", raw.visible_text, re.I)
            if m_open:
                visible["hours.open"] = m_open.group(1)
                hours.setdefault("open", m_open.group(1))
            # patterns like 5:00 AM - 11:00 PM
            m_range = re.search(
                r"(\d{1,2}:\d{2}\s*(?:AM|PM))\s*[-–]\s*(\d{1,2}:\d{2}\s*(?:AM|PM))",
                raw.visible_text,
                re.I,
            )
            if m_range:
                visible["hours.open"] = m_range.group(1)
                visible["hours.close"] = m_range.group(2)
                hours.setdefault("open", m_range.group(1))
                hours.setdefault("close", m_range.group(2))

        word_count = len(re.findall(r"\b\w+\b", raw.visible_text))
        description = raw.meta_description
        # Prefer longer unique paragraph if meta is generic brand text
        for para in raw.visible_text.split("\n"):
            if len(para) > 80 and address.city and address.city.lower() in para.lower():
                description = para
                break

        entity = LocationEntity(
            client=client_name,
            location_id=location_id,
            location_name=location_name,
            url=raw.url,
            canonical_url=raw.canonical,
            status_code=raw.status_code,
            indexable=is_indexable(raw.robots_meta),
            in_sitemap=in_sitemap,
            address=address,
            geo=geo,
            phone=phone,
            hours=hours,
            services=services,
            amenities=amenities,
            breadcrumbs=raw.breadcrumbs,
            nearby_locations=nearby,
            visible_faqs=raw.faqs,
            schema_entities=schema_entities,
            schema_types=collect_schema_types(schema_entities),
            visible_facts=visible,
            structured_facts=structured,
            local_content=LocalContent(
                description=description,
                word_count=word_count,
                unique_content_score=None,
            ),
            title=raw.title,
            meta_description=raw.meta_description,
        )
        entity.conflicts = self._build_conflicts(entity, raw)
        entity.findings.extend(self._technical_findings(entity, raw))
        return entity

    def _technical_findings(self, entity: LocationEntity, raw: RawPageData) -> list[EvidenceFinding]:
        findings: list[EvidenceFinding] = []
        findings.append(
            EvidenceFinding(
                check="status_200",
                result=raw.status_code == 200,
                evidence=f"HTTP {raw.status_code}",
                source="http",
            )
        )
        findings.append(
            EvidenceFinding(
                check="indexable",
                result=entity.indexable,
                evidence=raw.robots_meta or "no robots meta (assumed indexable)",
                source="meta",
            )
        )
        self_canon = self_referencing_canonical(raw.url, raw.canonical, raw.final_url)
        findings.append(
            EvidenceFinding(
                check="self_canonical",
                result=self_canon,
                evidence=raw.canonical,
                source="link[rel=canonical]",
            )
        )
        findings.append(
            EvidenceFinding(
                check="in_sitemap",
                result=entity.in_sitemap,
                evidence="URL present in location sitemap" if entity.in_sitemap else "Not confirmed in sitemap",
                source="sitemap",
            )
        )
        blocked = bool(raw.robots_meta and any(x in raw.robots_meta.lower() for x in ("noindex", "none")))
        findings.append(
            EvidenceFinding(
                check="no_blocking_robots",
                result=not blocked,
                evidence=raw.robots_meta,
                source="meta",
            )
        )
        return findings

    def _build_conflicts(self, entity: LocationEntity, raw: RawPageData) -> list[Conflict]:
        conflicts: list[Conflict] = []
        vis_addr = entity.visible_facts.get("address") or {}
        str_addr = entity.structured_facts.get("address") or {}
        if vis_addr.get("street") and str_addr.get("street"):
            match = addresses_match(vis_addr.get("street"), str_addr.get("street"))
            conflicts.append(
                Conflict(
                    attribute="address.street",
                    visible_value=vis_addr.get("street"),
                    structured_value=str_addr.get("street"),
                    status=ConflictStatus.MATCH if match else ConflictStatus.CONFLICT,
                    evidence=f"Visible: {vis_addr.get('street')} | Schema: {str_addr.get('street')}",
                )
            )
        elif str_addr.get("street") and not vis_addr.get("street"):
            conflicts.append(
                Conflict(
                    attribute="address.street",
                    visible_value=None,
                    structured_value=str_addr.get("street"),
                    status=ConflictStatus.MISSING,
                    evidence="Address present in schema but not clearly extracted from visible content",
                )
            )

        vis_phone = entity.visible_facts.get("phone")
        str_phone = entity.structured_facts.get("phone")
        if vis_phone and str_phone:
            conflicts.append(
                Conflict(
                    attribute="phone",
                    visible_value=str(vis_phone),
                    structured_value=str(str_phone),
                    status=ConflictStatus.MATCH if phones_match(str(vis_phone), str(str_phone)) else ConflictStatus.CONFLICT,
                    evidence=f"Visible: {vis_phone} | Schema: {str_phone}",
                )
            )

        # Hours open/close if both present
        v_open = entity.visible_facts.get("hours.open")
        s_hours = entity.structured_facts.get("hours") or {}
        s_open = None
        if isinstance(s_hours, dict) and entity.hours.get("open"):
            s_open = entity.hours.get("open")
        if v_open and s_open:
            # normalize times loosely
            def nt(t: str) -> str:
                return re.sub(r"\s+", "", t.lower()).replace(".", "")

            conflicts.append(
                Conflict(
                    attribute="hours.open",
                    visible_value=str(v_open),
                    structured_value=str(s_open),
                    status=ConflictStatus.MATCH if nt(str(v_open)) in nt(str(s_open)) or nt(str(s_open)) in nt(str(v_open)) else ConflictStatus.CONFLICT,
                    evidence=f"Visible open: {v_open} | Schema open: {s_open}",
                )
            )
        return conflicts
