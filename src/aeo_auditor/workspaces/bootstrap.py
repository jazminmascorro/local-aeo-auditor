"""Bootstrap helper: create/seed workspaces from client configs."""

from __future__ import annotations

from pathlib import Path

from aeo_auditor.client_config import ClientConfig, list_clients
from aeo_auditor.paths import project_path
from aeo_auditor.workspaces import WorkspaceStore
from aeo_auditor.workspaces.ingest import ingest_csv, ingest_url_list


def ensure_dutch_bros_workspace(store: WorkspaceStore | None = None) -> str:
    """Create dutch-bros workspace if missing and seed demo URLs + sample CSV."""
    store = store or WorkspaceStore()
    slug = "dutch-bros"
    if not store.exists(slug):
        cfg = ClientConfig.load("dutch-bros")
        assert cfg is not None
        store.create_workspace(
            cfg.client_name,
            slug=slug,
            allowed_domains=cfg.allowed_domains,
            location_url_pattern=cfg.location_url_pattern,
            location_url_min_path_segments=cfg.location_url_min_path_segments,
            sitemap_url=cfg.location_sitemap,
            expected_schema_types=cfg.expected_schema_types,
            business_type=cfg.business_type,
            question_sets=cfg.question_sets,
            client_config_slug="dutch-bros",
        )
    ws = store.get_workspace(slug)
    # Seed demo URLs if registry empty
    if not store.load_locations(slug) and cfg_demo_urls():
        ingest_url_list(store, ws, cfg_demo_urls(), source_label="demo_urls")
        ws = store.get_workspace(slug)
    # Seed sample CSV if present and not yet applied as csv source
    sample = project_path("clients", "dutch-bros", "sample_locations.csv")
    if sample.exists() and not any(s.type == "csv" for s in ws.sources):
        ingest_csv(store, ws, sample.read_bytes(), filename="sample_locations.csv")
    return slug


def cfg_demo_urls() -> list[str]:
    try:
        cfg = ClientConfig.load("dutch-bros")
        return list(cfg.demo_urls) if cfg else []
    except FileNotFoundError:
        return []


def ensure_workspace_from_client(client_slug: str, store: WorkspaceStore | None = None) -> str:
    store = store or WorkspaceStore()
    if client_slug == "dutch-bros":
        return ensure_dutch_bros_workspace(store)
    if store.exists(client_slug):
        return client_slug
    cfg = ClientConfig.load(client_slug)
    if cfg is None:
        raise FileNotFoundError(client_slug)
    store.create_workspace(
        cfg.client_name,
        slug=cfg.client_slug,
        allowed_domains=cfg.allowed_domains,
        location_url_pattern=cfg.location_url_pattern,
        location_url_min_path_segments=cfg.location_url_min_path_segments,
        sitemap_url=cfg.location_sitemap,
        expected_schema_types=cfg.expected_schema_types,
        business_type=cfg.business_type,
        question_sets=cfg.question_sets,
        client_config_slug=cfg.client_slug,
    )
    if cfg.demo_urls:
        ws = store.get_workspace(cfg.client_slug)
        ingest_url_list(store, ws, cfg.demo_urls, source_label="demo_urls")
    return cfg.client_slug


def sync_all_client_workspaces() -> list[str]:
    store = WorkspaceStore()
    return [ensure_workspace_from_client(c, store) for c in list_clients()]
