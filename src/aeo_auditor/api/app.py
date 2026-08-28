"""FastAPI enterprise workspace dashboard with Google auth + RQ audits."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from authlib.integrations.starlette_client import OAuth
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from aeo_auditor.auth import complete_login, current_user, get_auth_store
from aeo_auditor.auth.settings import auth_settings
from aeo_auditor.client_config import list_clients
from aeo_auditor.models import LocationEntity
from aeo_auditor.paths import PACKAGE_ROOT
from aeo_auditor.workspaces import WorkspaceStore
from aeo_auditor.workspaces.bootstrap import ensure_dutch_bros_workspace, ensure_workspace_from_client
from aeo_auditor.workspaces.ingest import ingest_csv, ingest_sitemap, ingest_url_list
from aeo_auditor.workspaces.jobs import enqueue_or_run_audit
from aeo_auditor.workers.queue import redis_available

settings = auth_settings()

app = FastAPI(
    title="Location Answerability Auditor",
    description="Enterprise multi-location AEO readiness — Google login, workspaces, CSV/sitemap, RQ audits.",
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings["session_secret"],
    same_site="lax",
    https_only=settings["session_https_only"],
)


class LoginRequired(Exception):
    def __init__(self, next_url: str = "/") -> None:
        self.next_url = next_url


class AccessDenied(Exception):
    def __init__(self, message: str = "Forbidden") -> None:
        self.message = message


@app.exception_handler(LoginRequired)
async def _login_required_handler(request: Request, exc: LoginRequired) -> RedirectResponse:
    return RedirectResponse(f"/auth/login?next={quote(exc.next_url)}", status_code=303)


@app.exception_handler(AccessDenied)
async def _access_denied_handler(request: Request, exc: AccessDenied) -> HTMLResponse:
    return HTMLResponse(
        f"<h1>Access denied</h1><p>{exc.message}</p><p><a href='/'>Home</a></p>",
        status_code=403,
    )


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise LoginRequired(str(request.url.path))
    return user


def require_workspace_access(request: Request, slug: str):
    user = require_user(request)
    if not get_auth_store().can_access(user.email, slug):
        raise AccessDenied("You do not have access to this workspace.")
    return user

templates = Jinja2Templates(directory=str(PACKAGE_ROOT / "templates"))
static_dir = PACKAGE_ROOT / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

store = WorkspaceStore()
oauth = OAuth()
if settings["google_enabled"]:
    oauth.register(
        name="google",
        client_id=settings["google_client_id"],
        client_secret=settings["google_client_secret"],
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

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


def _ctx(request: Request, **extra: Any) -> dict[str, Any]:
    user = current_user(request)
    return {
        "request": request,
        "user": user,
        "auth_dev_mode": settings["dev_mode"],
        "google_enabled": settings["google_enabled"],
        "redis_ok": redis_available(),
        "subtitle": SUBTITLE,
        **extra,
    }


@app.on_event("startup")
def _startup() -> None:
    try:
        ensure_dutch_bros_workspace(store)
    except Exception:
        pass


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "product": PRODUCT,
        "google_auth": settings["google_enabled"],
        "dev_auth": settings["dev_mode"],
        "redis": redis_available(),
    }


# ── Auth ─────────────────────────────────────────────────────────────


@app.get("/auth/login", response_class=HTMLResponse)
async def auth_login(request: Request, next: str = Query("/")) -> Any:
    if current_user(request):
        return RedirectResponse(next or "/", status_code=302)
    return templates.TemplateResponse(
        request,
        "login.html",
        _ctx(request, next_url=next or "/", flash=request.query_params.get("flash")),
    )


@app.get("/auth/google")
async def auth_google(request: Request, next: str = Query("/")) -> Any:
    if not settings["google_enabled"]:
        return RedirectResponse("/auth/login?flash=Google+login+is+not+configured", status_code=302)
    request.session["post_login_next"] = next or "/"
    redirect_uri = f"{settings['base_url']}/auth/callback"
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request) -> Any:
    if not settings["google_enabled"]:
        raise HTTPException(status_code=400, detail="Google auth disabled")
    token = await oauth.google.authorize_access_token(request)
    info = token.get("userinfo") or {}
    if not info and "id_token" in token:
        info = await oauth.google.parse_id_token(request, token)
    email = (info.get("email") or "").strip().lower()
    if not email:
        return RedirectResponse("/auth/login?flash=Google+did+not+return+an+email", status_code=302)
    complete_login(
        request,
        email=email,
        name=info.get("name"),
        picture=info.get("picture"),
        provider="google",
    )
    nxt = request.session.pop("post_login_next", "/")
    return RedirectResponse(nxt or "/", status_code=302)


@app.post("/auth/dev-login")
async def auth_dev_login(
    request: Request,
    email: str = Form("demo.analyst@example.com"),
    name: str = Form("Demo Analyst"),
    next: str = Form("/"),
) -> RedirectResponse:
    if not settings["dev_mode"]:
        raise HTTPException(status_code=403, detail="Dev login disabled")
    complete_login(request, email=email.strip().lower(), name=name.strip(), picture=None, provider="dev")
    return RedirectResponse(next or "/", status_code=303)


@app.post("/auth/logout")
@app.get("/auth/logout")
async def auth_logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# ── Workspaces ───────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> Any:
    ensure_dutch_bros_workspace(store)
    user = current_user(request)
    workspaces = store.list_workspaces()
    if user:
        allowed = set(get_auth_store().workspace_slugs_for(user.email))
        workspaces = [w for w in workspaces if w.slug in allowed]
    return templates.TemplateResponse(
        request,
        "workspaces.html",
        _ctx(
            request,
            workspaces=workspaces,
            clients=list_clients(),
            flash=request.query_params.get("flash"),
        ),
    )


@app.post("/workspaces/create")
async def create_workspace(
    request: Request,
    name: str = Form(...),
    allowed_domains: str = Form(""),
    location_url_pattern: str = Form("/locations/"),
    sitemap_url: str = Form(""),
    from_client: str = Form(""),
) -> RedirectResponse:
    user = require_user(request)
    auth = get_auth_store()
    if from_client.strip():
        slug = ensure_workspace_from_client(from_client.strip(), store)
        auth.add_membership(user.email, slug, role="admin")
        return RedirectResponse(f"/w/{slug}?flash=Workspace+ready", status_code=303)
    domains = [d.strip() for d in allowed_domains.split(",") if d.strip()]
    ws = store.create_workspace(
        name.strip(),
        allowed_domains=domains,
        location_url_pattern=location_url_pattern.strip() or "/locations/",
        sitemap_url=sitemap_url.strip() or None,
    )
    auth.add_membership(user.email, ws.slug, role="admin")
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
    require_workspace_access(request, slug)
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
    poll = bool(job and job.status in {"pending", "running"})
    return templates.TemplateResponse(
        request,
        "workspace.html",
        _ctx(
            request,
            ws=ws,
            locations=page_rows,
            total=total,
            audited=audited,
            page=page,
            pages=pages,
            page_size=page_size,
            sort=sort,
            order=order,
            q=q,
            job=job,
            summary=ws.portfolio_summary,
            flash=request.query_params.get("flash"),
            poll=poll,
            membership_role=get_auth_store().role_for(current_user(request).email, slug),  # type: ignore[union-attr]
        ),
    )


@app.get("/w/{slug}/sources", response_class=HTMLResponse)
async def sources_page(request: Request, slug: str) -> Any:
    require_workspace_access(request, slug)
    ws = store.get_workspace(slug)
    locations = store.load_locations(slug)
    return templates.TemplateResponse(
        request,
        "sources.html",
        _ctx(
            request,
            ws=ws,
            registry_count=len(locations),
            csv_count=sum(1 for l in locations if l.in_csv),
            sitemap_count=sum(1 for l in locations if l.in_sitemap),
            flash=request.query_params.get("flash"),
            error=request.query_params.get("error"),
        ),
    )


@app.post("/w/{slug}/sources/csv")
async def upload_csv(request: Request, slug: str, file: UploadFile = File(...)) -> RedirectResponse:
    require_workspace_access(request, slug)
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
    request: Request,
    slug: str,
    sitemap_url: str = Form(""),
    limit: str = Form(""),
) -> RedirectResponse:
    require_workspace_access(request, slug)
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
async def paste_urls(request: Request, slug: str, urls_text: str = Form("")) -> RedirectResponse:
    require_workspace_access(request, slug)
    ws = store.get_workspace(slug)
    urls = [line.strip() for line in urls_text.splitlines() if line.strip()]
    result = ingest_url_list(store, ws, urls, source_label="pasted_urls")
    flash = f"URLs:+{result['added']}+added.+Registry:+{result['total_registry']}"
    return RedirectResponse(f"/w/{slug}/sources?flash={flash}", status_code=303)


@app.post("/w/{slug}/audit")
async def start_audit(
    request: Request,
    slug: str,
    limit: str = Form("5"),
    use_cache: str = Form("on"),
    sync: str = Form(""),
) -> RedirectResponse:
    require_workspace_access(request, slug)
    lim = int(limit) if limit.strip().isdigit() else None
    if lim == 0:
        lim = None
    job, meta = enqueue_or_run_audit(
        store,
        slug,
        limit=lim,
        use_cache=use_cache == "on",
        force_sync=sync == "on",
    )
    if job.status == "failed":
        return RedirectResponse(f"/w/{slug}?flash={quote('Audit failed: ' + (job.error or ''))}", status_code=303)
    if meta.get("mode") == "async":
        flash = f"Audit+queued+({job.job_id}).+Worker+will+process+{job.total}+locations."
    else:
        flash = f"Audit+complete:+{job.completed}/{job.total}+({meta.get('mode')})"
    return RedirectResponse(f"/w/{slug}?flash={flash}", status_code=303)


@app.get("/w/{slug}/jobs/{job_id}")
async def job_status(request: Request, slug: str, job_id: str) -> dict[str, Any]:
    require_workspace_access(request, slug)
    job = store.get_job(slug, job_id)
    return job.model_dump(mode="json")


@app.get("/w/{slug}/location", response_class=HTMLResponse)
async def location_detail(request: Request, slug: str, url: str = Query(...)) -> Any:
    require_workspace_access(request, slug)
    ws = store.get_workspace(slug)
    entities = store.load_audit_entities(slug)
    raw = next((e for e in entities if e.get("url") == url), None)
    if not raw:
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
        _ctx(
            request,
            loc=loc,
            questions=questions,
            workspace_slug=slug,
            ws=ws,
            back_url=f"/w/{slug}",
        ),
    )


@app.post("/w/{slug}/members")
async def add_member(
    request: Request,
    slug: str,
    email: str = Form(...),
    role: str = Form("analyst"),
) -> RedirectResponse:
    user = require_workspace_access(request, slug)
    auth = get_auth_store()
    if auth.role_for(user.email, slug) != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    if role not in {"admin", "analyst", "viewer"}:
        role = "analyst"
    auth.add_membership(email.strip().lower(), slug, role=role)  # type: ignore[arg-type]
    return RedirectResponse(f"/w/{slug}?flash=Member+added", status_code=303)
