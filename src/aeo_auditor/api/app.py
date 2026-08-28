"""FastAPI dashboard application."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from aeo_auditor.client_config import ClientConfig, list_clients
from aeo_auditor.models import LocationEntity, PortfolioSummary
from aeo_auditor.paths import PACKAGE_ROOT, project_path
from aeo_auditor.pipeline import run_analysis

app = FastAPI(
    title="Location Answerability Auditor",
    description="Measure how clearly search engines and AI systems can understand and answer questions about every business location.",
)

templates = Jinja2Templates(directory=str(PACKAGE_ROOT / "templates"))
static_dir = PACKAGE_ROOT / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def output_dir() -> Path:
    return project_path("output")


def load_portfolio() -> PortfolioSummary | None:
    run_path = output_dir() / "run.json"
    if not run_path.exists():
        summary_path = output_dir() / "summary.json"
        if not summary_path.exists():
            return None
        # summary alone is not enough for detail pages
        return None
    data = json.loads(run_path.read_text(encoding="utf-8"))
    locations = [LocationEntity.model_validate(loc) for loc in data.get("locations", [])]
    summary = data.get("summary", {})
    return PortfolioSummary(
        client=summary.get("client", ""),
        locations_discovered=summary.get("locations_discovered", len(locations)),
        locations_crawled=summary.get("locations_crawled", len(locations)),
        average_aeo_score=summary.get("average_aeo_score", 0),
        category_averages=summary.get("category_averages", {}),
        score_distribution=summary.get("score_distribution", {}),
        systemic_opportunities=summary.get("systemic_opportunities", []),
        cross_location_stats=summary.get("cross_location_stats", {}),
        locations=locations,
    )


def mark(value: bool | None) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "partial"


templates.env.globals["mark"] = mark


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, sort: str = Query("aeo_score"), order: str = Query("desc")) -> Any:
    portfolio = load_portfolio()
    locations = list(portfolio.locations) if portfolio else []

    def sort_key(loc: LocationEntity) -> Any:
        sc = loc.scorecard
        mapping = {
            "aeo_score": sc.total if sc else -1,
            "discovery": sc.discovery.score if sc else -1,
            "entity": sc.entity_clarity.score if sc else -1,
            "schema": sc.structured_data.score if sc else -1,
            "answers": sc.answer_coverage.score if sc else -1,
            "uniqueness": sc.local_uniqueness.score if sc else -1,
            "city": loc.address.city or "",
            "state": loc.address.region or "",
            "location": loc.location_name or loc.url,
        }
        return mapping.get(sort, sc.total if sc else -1)

    reverse = order != "asc"
    if sort in {"city", "state", "location"}:
        locations.sort(key=lambda l: str(sort_key(l)).lower(), reverse=reverse)
    else:
        locations.sort(key=sort_key, reverse=reverse)

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "portfolio": portfolio,
            "locations": locations,
            "clients": list_clients(),
            "sort": sort,
            "order": order,
            "product_name": "Location Answerability Auditor",
            "subtitle": "Measure how clearly search engines and AI systems can understand and answer questions about every business location.",
        },
    )


@app.get("/location", response_class=HTMLResponse)
async def location_detail(request: Request, url: str = Query(...)) -> Any:
    portfolio = load_portfolio()
    if not portfolio:
        return RedirectResponse("/", status_code=302)
    loc = next((l for l in portfolio.locations if l.url == url), None)
    if not loc:
        return HTMLResponse(f"Location not found: {url}", status_code=404)
    questions = list(loc.answerable_questions.values())
    return templates.TemplateResponse(
        request,
        "location.html",
        {
            "loc": loc,
            "questions": questions,
            "product_name": "Location Answerability Auditor",
        },
    )


@app.post("/analyze")
async def analyze_form(
    client: str = Form(""),
    url: str = Form(""),
    demo: str = Form(""),
    limit: str = Form("5"),
) -> RedirectResponse:
    client_cfg = ClientConfig.load(client) if client else None
    limit_n = int(limit) if limit.strip().isdigit() else 5
    run_analysis(
        client=client_cfg,
        url=url.strip() or None,
        use_demo_urls=demo == "on" or (not url.strip() and client_cfg is not None),
        limit=limit_n,
        use_cache=True,
        output_dir=output_dir(),
    )
    return RedirectResponse("/", status_code=303)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "product": "Location Answerability Auditor"}
