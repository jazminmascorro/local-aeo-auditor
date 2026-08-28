"""FastAPI enterprise workspace dashboard."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from aeo_auditor.client_config import list_clients
from aeo_auditor.models import LocationEntity
from aeo_auditor.paths import PACKAGE_ROOT
from aeo_auditor.workspaces import WorkspaceStore
from aeo_auditor.workspaces.bootstrap import ensure_dutch_bros_workspace, ensure_workspace_from_client
from aeo_auditor.workspaces.ingest import ingest_csv, ingest_sitemap, ingest_url_list
from aeo_auditor.workspaces.jobs import run_audit_now

app = FastAPI(
    title="Location Answerability Auditor",
    description="Enterprise multi-location AEO readiness — workspaces, CSV upload, sitemap connect, portfolio audits.",
)

templates = Jinja2Templates(directory=str(PACKAGE_ROOT / "templates"))
static_dir = PACKAGE_ROOT / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

store = WorkspaceStore()

PRODUCT = "Location Answerability Auditor"
SUBTITLE = "Measure how clearly search engines and AI systems can understand and answer questions about every business location."


def mark(value: bool | None) -> str:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return "partial"


templates.env.globals["mark"] = mark
templates.env.globals["product_name"] = PRODUCT
templates.env.globals["quote"] = quote


@app.on_event("startup")
def _startup() -> None:
    try:
        ensure_dutch_bros_workspace(store)
    except Exception:
        pass


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "product": PRODUCT}


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> Any:
    ensure_dutch_bros_workspace(store)
    workspaces = store.list_workspaces()
    return templates.TemplateResponse(
        request,
        "workspaces.html",
        {
            "workspaces": workspaces,
            "clients": list_clients(),
            "subtitle": SUBTITLE,
            "flash": request.query_params.get("flash"),
        },
    )


@app.post("/workspaces/create")
async def create_workspace(
    name: str = Form(...),
    allowed_domains: str = Form(""),
    location_url_pattern: str = Form("/locations/"),
    sitemap_url: str = Form(""),
    from_client: str = Form(""),
) -> RedirectResponse:
    if from_client.strip():
        slug = ensure_workspace_from_client(from_client.strip(), store)
        return RedirectResponse(f"/w/{slug}?flash=Workspace+ready", status_code=303)
    domains = [d.strip() for d in allowed_domains.split(",") if d.strip()]
    ws = store.create_workspace(
        name.strip(),
        allowed_domains=domains,
        location_url_pattern=location_url_pattern.strip() or "/locations/",
        sitemap_url=sitemap_url.strip() or None,
    )
    return RedirectResponse(f"/w/{ws.slug}/sources?flash=Workspace+created", status_code=303)


@app.get("/w/{slug}", response_class=HTMLResponse)
async def workspace_home(
    request: Request,
    slug: str,
    sort: str = Query("aeo_score"),
    order: str = Query("desc"),
    q: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=5, le=100),
) -> Any:
    ws = store.get_workspace(slug)
    locations = store.load_locations(slug)
    if q.strip():
        needle = q.strip().lower()
        locations = [
            loc
            for loc in locations
            if needle in (loc.location_name or "").lower()
            or needle in (loc.city or "").lower()
            or needle in (loc.region or "").lower()
            or needle in loc.url.lower()
            or needle in (loc.location_id or "").lower()
        ]

    def sort_key(loc: Any) -> Any:
        mapping = {
            "aeo_score": loc.aeo_score if loc.aeo_score is not None else -1,
            "discovery": loc.discovery if loc.discovery is not None else -1,
            "entity": loc.entity_clarity if loc.entity_clarity is not None else -1,
            "schema": loc.structured_data if loc.structured_data is not None else -1,
            "answers": loc.answer_coverage if loc.answer_coverage is not None else -1,
            "uniqueness": loc.local_uniqueness if loc.local_uniqueness is not None else -1,
            "city": loc.city or "",
            "state": loc.region or "",
            "location": loc.location_name or loc.url,
        }
        return mapping.get(sort, loc.aeo_score if loc.aeo_score is not None else -1)

    reverse = order != "asc"
    if sort in {"city", "state", "location"}:
        locations.sort(key=lambda l: str(sort_key(l)).lower(), reverse=reverse)
    else:
        locations.sort(key=sort_key, reverse=reverse)

    total = len(locations)
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    start = (page - 1) * page_size
    page_rows = locations[start : start + page_size]
    job = store.latest_job(slug)
    audited = sum(1 for loc in store.load_locations(slug) if loc.last_audited_at)
    return templates.TemplateResponse(
        request,
        "workspace.html",
        {
            "ws": ws,
            "locations": page_rows,
            "total": total,
            "audited": audited,
            "page": page,
            "pages": pages,
            "page_size": page_size,
            "sort": sort,
            "order": order,
            "q": q,
            "job": job,
            "summary": ws.portfolio_summary,
            "flash": request.query_params.get("flash"),
            "subtitle": SUBTITLE,
        },
    )


@app.get("/w/{slug}/sources", response_class=HTMLResponse)
async def sources_page(request: Request, slug: str) -> Any:
    ws = store.get_workspace(slug)
    locations = store.load_locations(slug)
    return templates.TemplateResponse(
        request,
        "sources.html",
        {
            "ws": ws,
            "registry_count": len(locations),
            "csv_count": sum(1 for l in locations if l.in_csv),
            "sitemap_count": sum(1 for l in locations if l.in_sitemap),
            "flash": request.query_params.get("flash"),
            "error": request.query_params.get("error"),
        },
    )


@app.post("/w/{slug}/sources/csv")
async def upload_csv(slug: str, file: UploadFile = File(...)) -> RedirectResponse:
    ws = store.get_workspace(slug)
    content = await file.read()
    try:
        result = ingest_csv(store, ws, content, filename=file.filename or "locations.csv")
        flash = f"CSV+imported:+{result['added']}+added,+{result['updated']}+updated.+Registry:+{result['total_registry']}"
        return RedirectResponse(f"/w/{slug}/sources?flash={flash}", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/w/{slug}/sources?error={quote(str(exc))}", status_code=303)


@app.post("/w/{slug}/sources/sitemap")
async def connect_sitemap(
    slug: str,
    sitemap_url: str = Form(""),
    limit: str = Form(""),
) -> RedirectResponse:
    ws = store.get_workspace(slug)
    lim = int(limit) if limit.strip().isdigit() else None
    try:
        result = ingest_sitemap(store, ws, sitemap_url.strip() or None, limit=lim)
        if result.get("empty_body") or result.get("error") or result.get("location_urls_found", 0) == 0:
            flash = (
                f"Sitemap+connected+but+found+{result.get('location_urls_found', 0)}+location+URLs."
                f"+Registry+still+has+{result['total_registry']}+locations."
                f"+Upload+a+CSV+to+cover+the+full+network."
            )
        else:
            flash = f"Sitemap:+{result['added']}+added,+{result['updated']}+updated.+Registry:+{result['total_registry']}"
        return RedirectResponse(f"/w/{slug}/sources?flash={flash}", status_code=303)
    except Exception as exc:  # noqa: BLE001
        return RedirectResponse(f"/w/{slug}/sources?error={quote(str(exc))}", status_code=303)


@app.post("/w/{slug}/sources/urls")
async def paste_urls(slug: str, urls_text: str = Form("")) -> RedirectResponse:
    ws = store.get_workspace(slug)
    urls = [line.strip() for line in urls_text.splitlines() if line.strip()]
    result = ingest_url_list(store, ws, urls, source_label="pasted_urls")
    flash = f"URLs:+{result['added']}+added.+Registry:+{result['total_registry']}"
    return RedirectResponse(f"/w/{slug}/sources?flash={flash}", status_code=303)


@app.post("/w/{slug}/audit")
async def start_audit(
    slug: str,
    limit: str = Form("5"),
    use_cache: str = Form("on"),
) -> RedirectResponse:
    lim = int(limit) if limit.strip().isdigit() else None
    if lim == 0:
        lim = None
    job = run_audit_now(store, slug, limit=lim, use_cache=use_cache == "on")
    if job.status == "failed":
        return RedirectResponse(f"/w/{slug}?error={quote(job.error or 'Audit failed')}", status_code=303)
    flash = f"Audit+complete:+{job.completed}/{job.total}+locations"
    return RedirectResponse(f"/w/{slug}?flash={flash}", status_code=303)


@app.get("/w/{slug}/location", response_class=HTMLResponse)
async def location_detail(request: Request, slug: str, url: str = Query(...)) -> Any:
    ws = store.get_workspace(slug)
    entities = store.load_audit_entities(slug)
    raw = next((e for e in entities if e.get("url") == url), None)
    if not raw:
        # fall back to any entity in registry scores only message
        return HTMLResponse(
            f"No audit detail for this URL yet. Run an audit that includes it.<br/>"
            f"<a href='/w/{slug}'>Back</a>",
            status_code=404,
        )
    loc = LocationEntity.model_validate(raw)
    questions = list(loc.answerable_questions.values())
    return templates.TemplateResponse(
        request,
        "location.html",
        {
            "loc": loc,
            "questions": questions,
            "workspace_slug": slug,
            "ws": ws,
            "back_url": f"/w/{slug}",
        },
    )


# Legacy routes kept for old bookmarks / CLI output viewing
@app.get("/legacy", response_class=HTMLResponse)
async def legacy_home(request: Request) -> Any:
    return RedirectResponse("/", status_code=302)
