"""Portfolio aggregation and cross-location analysis."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from aeo_auditor.models import ConflictStatus, LocationEntity, PortfolioSummary
from aeo_auditor.scoring import band_for_score, load_scoring_config


def aggregate_portfolio(client_name: str, locations: list[LocationEntity], discovered: int | None = None) -> PortfolioSummary:
    cfg = load_scoring_config()
    crawled = len(locations)
    scores = [loc.scorecard.total for loc in locations if loc.scorecard]
    avg = round(sum(scores) / len(scores), 1) if scores else 0.0

    cat_sums: dict[str, list[float]] = defaultdict(list)
    for loc in locations:
        if not loc.scorecard:
            continue
        cat_sums["discovery"].append(loc.scorecard.discovery.score)
        cat_sums["entity_clarity"].append(loc.scorecard.entity_clarity.score)
        cat_sums["structured_data"].append(loc.scorecard.structured_data.score)
        cat_sums["answer_coverage"].append(loc.scorecard.answer_coverage.score)
        cat_sums["local_uniqueness"].append(loc.scorecard.local_uniqueness.score)

    category_averages = {
        k: round((sum(v) / len(v) / 20.0) * 100, 1) if v else 0.0 for k, v in cat_sums.items()
    }

    distribution: dict[str, int] = Counter()
    for s in scores:
        distribution[band_for_score(s, cfg)] += 1

    cross = cross_location_stats(locations)
    opportunities = systemic_opportunities(locations, cross)

    return PortfolioSummary(
        client=client_name,
        locations_discovered=discovered if discovered is not None else crawled,
        locations_crawled=crawled,
        average_aeo_score=avg,
        category_averages=category_averages,
        score_distribution=dict(distribution),
        systemic_opportunities=opportunities,
        cross_location_stats=cross,
        locations=locations,
    )


def cross_location_stats(locations: list[LocationEntity]) -> dict[str, Any]:
    n = len(locations) or 1
    drive_thru_stated = sum(1 for loc in locations if loc.services.drive_thru is True)
    walk_up_stated = sum(1 for loc in locations if loc.services.walk_up is True)
    pickup_stated = sum(1 for loc in locations if loc.services.pickup is True)
    missing_phone = sum(1 for loc in locations if not loc.phone)
    missing_geo = sum(1 for loc in locations if loc.geo.latitude is None)
    missing_hours = sum(1 for loc in locations if not loc.hours)
    low_uniqueness = sum(
        1 for loc in locations if loc.scorecard and loc.scorecard.local_uniqueness.score < 10
    )
    low_answers = sum(
        1
        for loc in locations
        if loc.scorecard and (loc.scorecard.answer_coverage.score / 20.0) < 0.5
    )
    conflicts = sum(
        1 for loc in locations if any(c.status == ConflictStatus.CONFLICT for c in loc.conflicts)
    )
    hours_conflicts = sum(
        1
        for loc in locations
        if any(c.attribute.startswith("hours") and c.status == ConflictStatus.CONFLICT for c in loc.conflicts)
    )
    word_counts = [loc.local_content.word_count for loc in locations]
    avg_words = round(sum(word_counts) / len(word_counts), 1) if word_counts else 0
    schema_type_sets = [tuple(sorted(loc.schema_types)) for loc in locations]
    schema_variance = len(set(schema_type_sets))

    # naming conventions
    names = [loc.location_name or "" for loc in locations]
    name_patterns = Counter(names)

    return {
        "drive_thru_explicit": drive_thru_stated,
        "drive_thru_missing": n - drive_thru_stated,
        "walk_up_explicit": walk_up_stated,
        "pickup_explicit": pickup_stated,
        "missing_phone": missing_phone,
        "missing_geo": missing_geo,
        "missing_hours": missing_hours,
        "low_answer_coverage": low_answers,
        "low_uniqueness": low_uniqueness,
        "locations_with_conflicts": conflicts,
        "hours_conflicts": hours_conflicts,
        "avg_word_count": avg_words,
        "schema_type_variants": schema_variance,
        "duplicate_names": sum(1 for _, c in name_patterns.items() if c > 1 and _),
        "n": n,
    }


def systemic_opportunities(locations: list[LocationEntity], cross: dict[str, Any]) -> list[str]:
    ops: list[str] = []
    n = cross.get("n") or len(locations)
    if cross.get("low_answer_coverage"):
        ops.append(f"{cross['low_answer_coverage']} locations have <50% answer coverage")
    if cross.get("drive_thru_missing"):
        ops.append(
            f"{cross['drive_thru_missing']} locations missing explicit drive-thru status "
            f"({cross.get('drive_thru_explicit', 0)} / {n} explicitly stated)"
        )
    services_missing = sum(
        1
        for loc in locations
        if not any(v is True for v in loc.services.model_dump().values())
    )
    if services_missing:
        ops.append(f"{services_missing} locations do not explicitly expose service attributes")
    if cross.get("low_uniqueness"):
        ops.append(f"{cross['low_uniqueness']} locations have weak local uniqueness")
    if cross.get("locations_with_conflicts"):
        ops.append(f"{cross['locations_with_conflicts']} locations contain structured/visible data inconsistencies")
    if cross.get("hours_conflicts"):
        ops.append(f"{cross['hours_conflicts']} locations contain possible hours conflicts")
    if cross.get("missing_phone"):
        ops.append(f"{cross['missing_phone']} locations missing phone numbers")
    if cross.get("schema_type_variants", 0) > 1:
        ops.append(f"Schema type variance across portfolio: {cross['schema_type_variants']} distinct type sets")
    return ops
