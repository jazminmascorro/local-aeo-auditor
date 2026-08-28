"""CSV / JSON / HTML report exporters."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from aeo_auditor.models import LocationEntity, PortfolioSummary


def ensure_output_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_locations_csv(locations: list[LocationEntity], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "client",
                "location_id",
                "location_name",
                "url",
                "city",
                "region",
                "postal_code",
                "phone",
                "status_code",
                "indexable",
                "word_count",
            ],
        )
        writer.writeheader()
        for loc in locations:
            writer.writerow(
                {
                    "client": loc.client,
                    "location_id": loc.location_id or "",
                    "location_name": loc.location_name or "",
                    "url": loc.url,
                    "city": loc.address.city or "",
                    "region": loc.address.region or "",
                    "postal_code": loc.address.postal_code or "",
                    "phone": loc.phone or "",
                    "status_code": loc.status_code or "",
                    "indexable": loc.indexable,
                    "word_count": loc.local_content.word_count,
                }
            )


def write_scores_csv(locations: list[LocationEntity], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "url",
                "location_name",
                "city",
                "region",
                "aeo_score",
                "band",
                "discovery",
                "entity_clarity",
                "structured_data",
                "answer_coverage",
                "local_uniqueness",
            ],
        )
        writer.writeheader()
        for loc in locations:
            sc = loc.scorecard
            writer.writerow(
                {
                    "url": loc.url,
                    "location_name": loc.location_name or "",
                    "city": loc.address.city or "",
                    "region": loc.address.region or "",
                    "aeo_score": sc.total if sc else "",
                    "band": sc.band if sc else "",
                    "discovery": sc.discovery.score if sc else "",
                    "entity_clarity": sc.entity_clarity.score if sc else "",
                    "structured_data": sc.structured_data.score if sc else "",
                    "answer_coverage": sc.answer_coverage.score if sc else "",
                    "local_uniqueness": sc.local_uniqueness.score if sc else "",
                }
            )


def write_answer_coverage_csv(locations: list[LocationEntity], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "url",
                "question_id",
                "category",
                "question",
                "fact_known",
                "visible_on_page",
                "structured",
                "explicitly_answered",
                "confidence",
                "evidence",
                "source",
            ],
        )
        writer.writeheader()
        for loc in locations:
            for qid, qr in loc.answerable_questions.items():
                writer.writerow(
                    {
                        "url": loc.url,
                        "question_id": qr.question_id,
                        "category": qr.category,
                        "question": qr.question,
                        "fact_known": qr.fact_known,
                        "visible_on_page": qr.visible_on_page,
                        "structured": qr.structured,
                        "explicitly_answered": qr.explicitly_answered,
                        "confidence": qr.confidence,
                        "evidence": qr.evidence or "",
                        "source": qr.source or "",
                    }
                )


def write_schema_findings_csv(locations: list[LocationEntity], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["url", "schema_types", "valid_entities", "parse_errors", "structured_facts_keys"],
        )
        writer.writeheader()
        for loc in locations:
            writer.writerow(
                {
                    "url": loc.url,
                    "schema_types": "|".join(loc.schema_types),
                    "valid_entities": sum(1 for e in loc.schema_entities if e.valid and e.types),
                    "parse_errors": "|".join(e.parse_error or "" for e in loc.schema_entities if e.parse_error),
                    "structured_facts_keys": "|".join(sorted(loc.structured_facts.keys())),
                }
            )


def write_issues_csv(locations: list[LocationEntity], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["url", "type", "attribute", "status", "evidence"],
        )
        writer.writeheader()
        for loc in locations:
            for c in loc.conflicts:
                writer.writerow(
                    {
                        "url": loc.url,
                        "type": "conflict",
                        "attribute": c.attribute,
                        "status": c.status.value,
                        "evidence": c.evidence or "",
                    }
                )
            for opp in loc.opportunities:
                writer.writerow(
                    {
                        "url": loc.url,
                        "type": "opportunity",
                        "attribute": "",
                        "status": "",
                        "evidence": opp,
                    }
                )


def write_recommendations_csv(locations: list[LocationEntity], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["url", "priority", "title", "message", "evidence"],
        )
        writer.writeheader()
        for loc in locations:
            for rec in loc.recommendations:
                writer.writerow(
                    {
                        "url": loc.url,
                        "priority": rec.priority.value,
                        "title": rec.title,
                        "message": rec.message,
                        "evidence": rec.evidence or "",
                    }
                )


def summary_dict(portfolio: PortfolioSummary) -> dict[str, Any]:
    return {
        "client": portfolio.client,
        "locations_discovered": portfolio.locations_discovered,
        "locations_crawled": portfolio.locations_crawled,
        "average_aeo_score": portfolio.average_aeo_score,
        "category_averages": portfolio.category_averages,
        "score_distribution": portfolio.score_distribution,
        "systemic_opportunities": portfolio.systemic_opportunities,
        "cross_location_stats": portfolio.cross_location_stats,
        "locations": [
            {
                "url": loc.url,
                "location_name": loc.location_name,
                "city": loc.address.city,
                "region": loc.address.region,
                "scorecard": loc.scorecard.as_dict() if loc.scorecard else None,
                "location_id": loc.location_id,
            }
            for loc in portfolio.locations
        ],
    }


def write_summary_json(portfolio: PortfolioSummary, path: Path) -> None:
    path.write_text(json.dumps(summary_dict(portfolio), indent=2), encoding="utf-8")


def write_full_run_json(portfolio: PortfolioSummary, path: Path) -> None:
    payload = {
        "summary": summary_dict(portfolio),
        "locations": [loc.model_dump(mode="json") for loc in portfolio.locations],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_aeo_report_html(portfolio: PortfolioSummary, path: Path) -> None:
    rows = []
    for loc in sorted(portfolio.locations, key=lambda l: -(l.scorecard.total if l.scorecard else 0)):
        sc = loc.scorecard
        rows.append(
            "<tr>"
            f"<td>{_esc(loc.location_name or loc.url)}</td>"
            f"<td>{_esc(loc.address.city)}</td>"
            f"<td>{_esc(loc.address.region)}</td>"
            f"<td><a href=\"{_esc(loc.url)}\">{_esc(loc.url)}</a></td>"
            f"<td>{sc.total if sc else ''}</td>"
            f"<td>{sc.discovery.score if sc else ''}</td>"
            f"<td>{sc.entity_clarity.score if sc else ''}</td>"
            f"<td>{sc.structured_data.score if sc else ''}</td>"
            f"<td>{sc.answer_coverage.score if sc else ''}</td>"
            f"<td>{sc.local_uniqueness.score if sc else ''}</td>"
            "</tr>"
        )
    ops = "".join(f"<li>{_esc(o)}</li>" for o in portfolio.systemic_opportunities)
    dist = "".join(f"<li>{_esc(k)}: {v}</li>" for k, v in portfolio.score_distribution.items())
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Location Answerability Auditor — {_esc(portfolio.client)}</title>
<style>
body{{font-family:Georgia,serif;margin:2rem;background:#f7f4ef;color:#1a2330}}
h1,h2{{font-family:Arial,Helvetica,sans-serif;color:#0c3b5e}}
.card{{background:#fff;padding:1.25rem 1.5rem;margin-bottom:1.5rem;border:1px solid #d9d2c5}}
table{{width:100%;border-collapse:collapse;font-size:0.92rem}}
th,td{{border-bottom:1px solid #e5dfd3;padding:0.5rem;text-align:left}}
th{{background:#0c3b5e;color:#fff}}
.muted{{color:#5a6573}}
</style>
</head>
<body>
<h1>Location Answerability Auditor</h1>
<p class="muted">Measure how clearly search engines and AI systems can understand and answer questions about every business location.</p>
<div class="card">
<h2>Multi-Location AEO Report — {_esc(portfolio.client)}</h2>
<ul>
<li>Locations discovered: {portfolio.locations_discovered}</li>
<li>Locations crawled: {portfolio.locations_crawled}</li>
<li>Average AEO score: {portfolio.average_aeo_score}</li>
<li>Discovery average: {portfolio.category_averages.get('discovery', 0)}%</li>
<li>Entity clarity: {portfolio.category_averages.get('entity_clarity', 0)}%</li>
<li>Structured data: {portfolio.category_averages.get('structured_data', 0)}%</li>
<li>Answer coverage: {portfolio.category_averages.get('answer_coverage', 0)}%</li>
<li>Local uniqueness: {portfolio.category_averages.get('local_uniqueness', 0)}%</li>
</ul>
</div>
<div class="card">
<h2>Score distribution</h2>
<ul>{dist}</ul>
</div>
<div class="card">
<h2>Portfolio-wide opportunities</h2>
<ul>{ops or '<li>None detected in this run</li>'}</ul>
</div>
<div class="card">
<h2>Locations</h2>
<table>
<thead><tr>
<th>Location</th><th>City</th><th>State</th><th>URL</th>
<th>AEO</th><th>Discovery</th><th>Entity</th><th>Schema</th><th>Answers</th><th>Uniqueness</th>
</tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
</div>
<p class="muted">AEO Readiness Score is a proprietary diagnostic framework, not a Google/OpenAI/Bing/Yext metric.</p>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def _esc(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def export_all(portfolio: PortfolioSummary, output_dir: Path) -> dict[str, Path]:
    out = ensure_output_dir(output_dir)
    paths = {
        "locations.csv": out / "locations.csv",
        "location_scores.csv": out / "location_scores.csv",
        "answer_coverage.csv": out / "answer_coverage.csv",
        "schema_findings.csv": out / "schema_findings.csv",
        "issues.csv": out / "issues.csv",
        "recommendations.csv": out / "recommendations.csv",
        "summary.json": out / "summary.json",
        "run.json": out / "run.json",
        "aeo-report.html": out / "aeo-report.html",
    }
    write_locations_csv(portfolio.locations, paths["locations.csv"])
    write_scores_csv(portfolio.locations, paths["location_scores.csv"])
    write_answer_coverage_csv(portfolio.locations, paths["answer_coverage.csv"])
    write_schema_findings_csv(portfolio.locations, paths["schema_findings.csv"])
    write_issues_csv(portfolio.locations, paths["issues.csv"])
    write_recommendations_csv(portfolio.locations, paths["recommendations.csv"])
    write_summary_json(portfolio, paths["summary.json"])
    write_full_run_json(portfolio, paths["run.json"])
    write_aeo_report_html(portfolio, paths["aeo-report.html"])
    return paths
