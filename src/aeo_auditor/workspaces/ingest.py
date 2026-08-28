"""Ingest locations from CSV and sitemaps into a workspace registry."""

from __future__ import annotations

import csv
import io
from typing import Any

from aeo_auditor.sitemap import discover_location_urls
from aeo_auditor.workspaces import RegisteredLocation, Workspace, WorkspaceSource, WorkspaceStore, utc_now


CSV_ALIASES = {
    "url": {"url", "page_url", "location_url", "store_url", "website", "link"},
    "location_id": {"location_id", "id", "store_id", "entity_id", "store_code"},
    "location_name": {"location_name", "name", "store_name", "title"},
    "city": {"city", "address_city", "locality"},
    "region": {"region", "state", "address_region", "province"},
    "postal_code": {"postal_code", "zip", "zip_code", "postcode"},
    "phone": {"phone", "telephone", "phone_number"},
}


def _map_header(header: str) -> str | None:
    h = header.strip().lower().replace(" ", "_")
    for canonical, aliases in CSV_ALIASES.items():
        if h in aliases:
            return canonical
    return None


def parse_locations_csv(content: str | bytes) -> tuple[list[RegisteredLocation], dict[str, Any]]:
    if isinstance(content, bytes):
        text = content.decode("utf-8-sig")
    else:
        text = content.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV has no header row")
    mapping: dict[str, str] = {}
    for field in reader.fieldnames:
        canon = _map_header(field)
        if canon:
            mapping[canon] = field
    if "url" not in mapping:
        raise ValueError(
            "CSV must include a URL column (url, location_url, store_url, website, or link)"
        )

    locations: list[RegisteredLocation] = []
    skipped = 0
    for row in reader:
        url = (row.get(mapping["url"]) or "").strip()
        if not url or not url.startswith(("http://", "https://")):
            skipped += 1
            continue
        locations.append(
            RegisteredLocation(
                url=url,
                location_id=_cell(row, mapping, "location_id"),
                location_name=_cell(row, mapping, "location_name"),
                city=_cell(row, mapping, "city"),
                region=_cell(row, mapping, "region"),
                postal_code=_cell(row, mapping, "postal_code"),
                phone=_cell(row, mapping, "phone"),
                sources=["csv"],
                in_csv=True,
            )
        )
    meta = {
        "rows_parsed": len(locations),
        "rows_skipped": skipped,
        "mapped_columns": mapping,
    }
    return locations, meta


def _cell(row: dict[str, str | None], mapping: dict[str, str], key: str) -> str | None:
    col = mapping.get(key)
    if not col:
        return None
    val = (row.get(col) or "").strip()
    return val or None


def ingest_csv(
    store: WorkspaceStore,
    workspace: Workspace,
    content: str | bytes,
    *,
    filename: str = "locations.csv",
) -> dict[str, Any]:
    locations, parse_meta = parse_locations_csv(content)
    added, updated, merged = store.upsert_locations(workspace.slug, locations, source="csv")
    # persist upload
    upload_path = store.uploads_dir(workspace.slug) / f"{utc_now().replace(':', '')}_{filename}"
    raw = content if isinstance(content, bytes) else content.encode("utf-8")
    upload_path.write_bytes(raw)

    source = WorkspaceSource(
        type="csv",
        label=filename,
        detail=f"{added} added, {updated} updated",
        connected_at=utc_now(),
        location_count=len(locations),
        meta={**parse_meta, "upload_path": str(upload_path)},
    )
    workspace.sources = [s for s in workspace.sources if not (s.type == "csv" and s.label == filename)]
    workspace.sources.insert(0, source)
    store.save_workspace(workspace)
    return {
        "added": added,
        "updated": updated,
        "total_registry": len(merged),
        "parsed": len(locations),
        "skipped": parse_meta["rows_skipped"],
        "mapped_columns": parse_meta["mapped_columns"],
    }


def ingest_sitemap(
    store: WorkspaceStore,
    workspace: Workspace,
    sitemap_url: str | None = None,
    *,
    limit: int | None = None,
) -> dict[str, Any]:
    sitemap_url = (sitemap_url or workspace.sitemap_url or "").strip()
    if not sitemap_url:
        raise ValueError("Sitemap URL is required")

    result = discover_location_urls(
        sitemap_url,
        pattern=workspace.location_url_pattern,
        allowed_domains=workspace.allowed_domains or None,
        min_path_segments=workspace.location_url_min_path_segments,
        limit=limit,
    )
    workspace.sitemap_url = sitemap_url
    locations = [
        RegisteredLocation(url=u, sources=["sitemap"], in_sitemap=True)
        for u in result.location_urls
    ]
    # Mark existing URLs not in this sitemap pull as in_sitemap=False only if we got a successful non-empty parse
    added, updated, merged = store.upsert_locations(workspace.slug, locations, source="sitemap")
    if result.location_urls:
        found = {store._norm_url(u) for u in result.location_urls}
        for loc in merged:
            if store._norm_url(loc.url) in found:
                loc.in_sitemap = True
            elif loc.in_sitemap is None:
                loc.in_sitemap = False
        store.save_locations(workspace.slug, merged)

    source = WorkspaceSource(
        type="sitemap",
        label=sitemap_url,
        detail=result.error or ("empty body" if result.empty_body else f"{len(result.location_urls)} location URLs"),
        connected_at=utc_now(),
        location_count=len(result.location_urls),
        meta={
            "status_code": result.status_code,
            "empty_body": result.empty_body,
            "error": result.error,
            "urls_found": len(result.urls),
            "location_urls_found": len(result.location_urls),
        },
    )
    workspace.sources = [s for s in workspace.sources if s.type != "sitemap"]
    workspace.sources.insert(0, source)
    store.save_workspace(workspace)
    return {
        "added": added,
        "updated": updated,
        "total_registry": len(merged),
        "sitemap_status_code": result.status_code,
        "empty_body": result.empty_body,
        "error": result.error,
        "urls_found": len(result.urls),
        "location_urls_found": len(result.location_urls),
    }


def ingest_url_list(
    store: WorkspaceStore,
    workspace: Workspace,
    urls: list[str],
    *,
    source_label: str = "url_list",
) -> dict[str, Any]:
    locations = [
        RegisteredLocation(url=u.strip(), sources=[source_label])
        for u in urls
        if u.strip().startswith(("http://", "https://"))
    ]
    added, updated, merged = store.upsert_locations(workspace.slug, locations, source=source_label)
    source = WorkspaceSource(
        type="urls",
        label=source_label,
        detail=f"{len(locations)} URLs",
        connected_at=utc_now(),
        location_count=len(locations),
    )
    workspace.sources.insert(0, source)
    store.save_workspace(workspace)
    return {"added": added, "updated": updated, "total_registry": len(merged), "parsed": len(locations)}
