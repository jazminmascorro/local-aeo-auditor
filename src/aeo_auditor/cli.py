"""Typer CLI for Location Answerability Auditor."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from aeo_auditor.client_config import ClientConfig, list_clients
from aeo_auditor.paths import project_path
from aeo_auditor.pipeline import run_analysis
from aeo_auditor.reporting import export_all

app = typer.Typer(
    name="aeo",
    help="Location Answerability Auditor — multi-location AEO readiness analysis",
    add_completion=False,
)
console = Console()


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


@app.command("clients")
def clients_cmd() -> None:
    """List available client configurations."""
    clients = list_clients()
    if not clients:
        console.print("No clients found under clients/")
        return
    for c in clients:
        console.print(f"- {c}")


@app.command("analyze")
def analyze_cmd(
    url: Optional[str] = typer.Option(None, "--url", help="Single location URL"),
    urls_file: Optional[Path] = typer.Option(None, "--urls-file", help="File with one URL per line"),
    sitemap: Optional[str] = typer.Option(None, "--sitemap", help="Location sitemap URL"),
    client: Optional[str] = typer.Option(None, "--client", help="Client slug (e.g. dutch-bros)"),
    demo: bool = typer.Option(False, "--demo", help="Use client demo_urls.txt"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Max URLs to analyze"),
    output: Path = typer.Option(Path("output"), "--output", "-o", help="Output directory"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass page cache"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Analyze one URL, a URL list, a sitemap, or a client demo set."""
    _setup_logging(verbose)
    client_cfg = ClientConfig.load(client) if client else None
    if client and client_cfg is None:
        raise typer.BadParameter(f"Unknown client: {client}")

    try:
        portfolio, meta = run_analysis(
            client=client_cfg,
            url=url,
            urls_file=urls_file,
            sitemap=sitemap,
            use_demo_urls=demo,
            limit=limit,
            use_cache=not no_cache,
            output_dir=output,
        )
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Analysis failed:[/red] {exc}")
        raise typer.Exit(1) from exc

    console.print(f"\n[bold]{portfolio.client or 'Run'} — AEO Portfolio[/bold]")
    console.print(f"Source: {meta.get('source')}")
    if meta.get("sitemap_result"):
        console.print(f"Sitemap: {json.dumps(meta['sitemap_result'])}")
    if meta.get("fallback_reason"):
        console.print(f"[yellow]Fallback:[/yellow] {meta['fallback_reason']}")
    console.print(f"Locations crawled: {portfolio.locations_crawled}")
    console.print(f"Average AEO score: {portfolio.average_aeo_score}")

    table = Table(title="Location scores")
    table.add_column("Location")
    table.add_column("City")
    table.add_column("Score", justify="right")
    table.add_column("Band")
    for loc in portfolio.locations:
        sc = loc.scorecard
        table.add_row(
            (loc.location_name or loc.url)[:48],
            loc.address.city or "",
            f"{sc.total:.0f}" if sc else "",
            sc.band if sc else "",
        )
    console.print(table)
    console.print(f"\nExports written to [bold]{output}[/bold]")
    for name, path in (meta.get("export_paths") or {}).items():
        console.print(f"  - {name}: {path}")


@app.command("serve")
def serve_cmd(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Start the dashboard (FastAPI)."""
    import uvicorn

    uvicorn.run("aeo_auditor.api.app:app", host=host, port=port, reload=reload)


@app.command("export")
def export_cmd(
    run_json: Path = typer.Option(Path("output/run.json"), "--run", help="Existing run.json"),
    output: Path = typer.Option(Path("output"), "--output", "-o"),
) -> None:
    """Re-export CSV/HTML from an existing run.json."""
    from aeo_auditor.models import LocationEntity, PortfolioSummary

    if not run_json.exists():
        console.print(f"[red]Missing[/red] {run_json}")
        raise typer.Exit(1)
    data = json.loads(run_json.read_text(encoding="utf-8"))
    locations = [LocationEntity.model_validate(loc) for loc in data.get("locations", [])]
    summary = data.get("summary", {})
    portfolio = PortfolioSummary(
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
    paths = export_all(portfolio, output)
    console.print(f"Re-exported {len(paths)} files to {output}")


workspace_app = typer.Typer(help="Enterprise workspace commands")
app.add_typer(workspace_app, name="workspace")


@workspace_app.command("list")
def workspace_list() -> None:
    from aeo_auditor.workspaces import WorkspaceStore
    from aeo_auditor.workspaces.bootstrap import ensure_dutch_bros_workspace

    store = WorkspaceStore()
    ensure_dutch_bros_workspace(store)
    for ws in store.list_workspaces():
        n = len(store.load_locations(ws.slug))
        console.print(f"- {ws.slug}: {ws.name} ({n} locations)")


@workspace_app.command("seed")
def workspace_seed(client: str = typer.Option("dutch-bros", "--client")) -> None:
    from aeo_auditor.workspaces.bootstrap import ensure_workspace_from_client

    slug = ensure_workspace_from_client(client)
    console.print(f"Seeded workspace [bold]{slug}[/bold]")


@workspace_app.command("import-csv")
def workspace_import_csv(
    slug: str = typer.Argument(...),
    csv_path: Path = typer.Argument(..., exists=True),
) -> None:
    from aeo_auditor.workspaces import WorkspaceStore
    from aeo_auditor.workspaces.ingest import ingest_csv

    store = WorkspaceStore()
    ws = store.get_workspace(slug)
    result = ingest_csv(store, ws, csv_path.read_bytes(), filename=csv_path.name)
    console.print(result)


@workspace_app.command("import-sitemap")
def workspace_import_sitemap(
    slug: str = typer.Argument(...),
    sitemap: Optional[str] = typer.Option(None, "--sitemap"),
    limit: Optional[int] = typer.Option(None, "--limit"),
) -> None:
    from aeo_auditor.workspaces import WorkspaceStore
    from aeo_auditor.workspaces.ingest import ingest_sitemap

    store = WorkspaceStore()
    ws = store.get_workspace(slug)
    result = ingest_sitemap(store, ws, sitemap, limit=limit)
    console.print(result)


@workspace_app.command("audit")
def workspace_audit(
    slug: str = typer.Argument(...),
    limit: Optional[int] = typer.Option(5, "--limit"),
    no_cache: bool = typer.Option(False, "--no-cache"),
    sync: bool = typer.Option(False, "--sync", help="Run inline instead of RQ"),
) -> None:
    from aeo_auditor.workspaces import WorkspaceStore
    from aeo_auditor.workspaces.jobs import enqueue_or_run_audit

    store = WorkspaceStore()
    job, meta = enqueue_or_run_audit(
        store, slug, limit=limit, use_cache=not no_cache, force_sync=sync
    )
    console.print(f"Job {job.job_id}: {job.status} — {job.message} [{meta.get('mode')}]")
    if job.error:
        console.print(f"[red]{job.error}[/red]")
        raise typer.Exit(1)


@app.command("worker")
def worker_cmd(
    burst: bool = typer.Option(False, "--burst", help="Process queued jobs then exit"),
) -> None:
    """Run an RQ worker that processes portfolio audit jobs."""
    from rq import Worker

    from aeo_auditor.workers.queue import QUEUE_NAME, redis_conn, redis_available

    if not redis_available():
        console.print("[red]Redis is not reachable. Start Redis and set REDIS_URL if needed.[/red]")
        raise typer.Exit(1)
    console.print(f"Listening on queue [bold]{QUEUE_NAME}[/bold]…")
    Worker([QUEUE_NAME], connection=redis_conn()).work(burst=burst)


if __name__ == "__main__":
    app()
