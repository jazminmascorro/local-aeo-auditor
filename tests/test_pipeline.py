"""Core pipeline tests using local HTML fixtures (no live network required)."""

from __future__ import annotations

from pathlib import Path

from aeo_auditor.entities import LocationNormalizer, addresses_match
from aeo_auditor.parser import raw_from_html
from aeo_auditor.pipeline import analyze_raw
from aeo_auditor.schema import extract_schema_entities, flatten_json_ld
from aeo_auditor.sitemap import filter_location_urls, parse_sitemap_xml

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_valid_location_extracts_entity_and_score():
    raw = raw_from_html("https://example.com/locations/az/phoenix/100-main-st", _load("valid_location.html"))
    entity = analyze_raw(raw)
    assert entity.status_code == 200
    assert entity.address.city == "Phoenix"
    assert entity.phone
    assert entity.geo.latitude is not None
    assert entity.services.drive_thru is True
    assert entity.services.pickup is True
    assert entity.location_id == "AZ0001"
    assert entity.scorecard is not None
    assert entity.scorecard.total > 40
    assert any(q.explicitly_answered for q in entity.answerable_questions.values())


def test_missing_canonical():
    raw = raw_from_html("https://example.com/locations/tx/austin/x", _load("missing_canonical.html"))
    entity = analyze_raw(raw)
    finding = next(f for f in entity.findings if f.check == "self_canonical")
    assert finding.result is None or finding.result is False


def test_no_structured_data():
    raw = raw_from_html("https://example.com/locations/co/denver/50-market", _load("no_schema.html"))
    entity = analyze_raw(raw)
    assert not any(e.valid and e.types for e in entity.schema_entities)
    assert entity.scorecard is not None
    assert entity.scorecard.structured_data.score < 10


def test_multiple_json_ld_blocks():
    raw = raw_from_html("https://example.com/locations/co/denver/9-pine", _load("multi_jsonld.html"))
    entities = extract_schema_entities(raw.json_ld_blocks)
    types = {t for e in entities for t in e.types}
    assert "Organization" in types
    assert "LocalBusiness" in types
    entity = analyze_raw(raw)
    assert entity.phone


def test_address_normalization_match():
    assert addresses_match("2961 E Bell Rd", "2961 East Bell Road")


def test_hours_conflict_or_visible_hours():
    raw = raw_from_html("https://example.com/locations/tx/austin/1-congress", _load("hours_conflict.html"))
    entity = analyze_raw(raw)
    assert entity.hours.get("close") == "22:00" or entity.visible_facts.get("hours.close")
    # Visible shows 11:00 PM close while schema says 22:00 — conflict if both extracted as open/close pairs
    # At minimum schema hours exist
    assert entity.structured_facts.get("hours")


def test_incomplete_address():
    raw = raw_from_html("https://example.com/locations/wa/seattle/x", _load("incomplete_address.html"))
    entity = analyze_raw(raw)
    assert entity.address.street is None
    assert entity.address.city == "Seattle"


def test_boilerplate_uniqueness_penalty():
    raw = raw_from_html("https://example.com/locations/or/portland/1-test", _load("duplicate_boilerplate.html"))
    entity = analyze_raw(raw)
    assert entity.scorecard is not None
    assert entity.scorecard.local_uniqueness.score <= 12


def test_non_indexable_page():
    raw = raw_from_html("https://example.com/locations/nv/vegas/1-strip", _load("noindex.html"))
    entity = analyze_raw(raw)
    assert entity.indexable is False
    finding = next(f for f in entity.findings if f.check == "indexable")
    assert finding.result is False


def test_malformed_schema():
    raw = raw_from_html("https://example.com/locations/id/boise/77-error", _load("malformed_schema.html"))
    # parser may salvage or record error
    entity = analyze_raw(raw)
    assert entity.location_name


def test_unanswered_questions_surface_missing():
    raw = raw_from_html("https://example.com/locations/ut/slc/1-state", _load("unanswered.html"))
    entity = analyze_raw(raw)
    assert entity.missing_answers
    assert any(not q.explicitly_answered for q in entity.answerable_questions.values())


def test_sitemap_parse_and_filter():
    xml = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://www.example.com/locations/az/phoenix/a</loc></url>
      <url><loc>https://www.example.com/menu/coffee</loc></url>
      <url><loc>https://www.example.com/locations/az</loc></url>
    </urlset>
    """
    result = parse_sitemap_xml(xml, "https://www.example.com/locations/sitemap.xml")
    assert len(result.urls) == 3
    filtered = filter_location_urls(
        result.urls,
        pattern="/locations/",
        allowed_domains=["example.com"],
        min_path_segments=3,
    )
    assert filtered == ["https://www.example.com/locations/az/phoenix/a"]


def test_empty_sitemap_body():
    result = parse_sitemap_xml("", "https://www.example.com/locations/sitemap.xml")
    assert result.empty_body
    assert result.error


def test_flatten_graph():
    blocks = [{"@graph": [{"@type": "WebPage"}, {"@type": ["LocalBusiness", "Restaurant"]}]}]
    flat = flatten_json_ld(blocks)
    assert len(flat) == 2
