"""Workspace + location registry persistence (file-backed, no auth yet)."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from aeo_auditor.paths import project_path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "workspace"


class RegisteredLocation(BaseModel):
    location_id: str | None = None
    location_name: str | None = None
    city: str | None = None
    region: str | None = None
    postal_code: str | None = None
    url: str
    phone: str | None = None
    sources: list[str] = Field(default_factory=list)
    in_sitemap: bool | None = None
    in_csv: bool | None = None
    last_audited_at: str | None = None
    aeo_score: float | None = None
    band: str | None = None
    discovery: float | None = None
    entity_clarity: float | None = None
    structured_data: float | None = None
    answer_coverage: float | None = None
    local_uniqueness: float | None = None
    issues_count: int = 0
    audit_entity: dict[str, Any] | None = None


class WorkspaceSource(BaseModel):
    type: str  # sitemap | csv | urls | demo
    label: str
    detail: str | None = None
    connected_at: str
    location_count: int = 0
    meta: dict[str, Any] = Field(default_factory=dict)


class Workspace(BaseModel):
    slug: str
    name: str
    created_at: str
    updated_at: str
    allowed_domains: list[str] = Field(default_factory=list)
    location_url_pattern: str = "/locations/"
    location_url_min_path_segments: int = 0
    sitemap_url: str | None = None
    expected_schema_types: list[str] = Field(default_factory=list)
    business_type: str | None = None
    question_sets: list[str] = Field(default_factory=list)
    client_config_slug: str | None = None
    sources: list[WorkspaceSource] = Field(default_factory=list)
    last_job_id: str | None = None
    last_audit_at: str | None = None
    portfolio_summary: dict[str, Any] | None = None


class AuditJob(BaseModel):
    job_id: str
    workspace_slug: str
    status: str = "pending"  # pending|running|completed|failed
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    total: int = 0
    completed: int = 0
    limit: int | None = None
    use_cache: bool = True
    error: str | None = None
    message: str | None = None


class WorkspaceStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or project_path("data", "workspaces")
        self.root.mkdir(parents=True, exist_ok=True)

    def list_workspaces(self) -> list[Workspace]:
        items: list[Workspace] = []
        for path in sorted(self.root.iterdir()):
            meta = path / "workspace.json"
            if path.is_dir() and meta.exists():
                items.append(Workspace.model_validate(json.loads(meta.read_text(encoding="utf-8"))))
        return items

    def workspace_dir(self, slug: str) -> Path:
        return self.root / slug

    def exists(self, slug: str) -> bool:
        return (self.workspace_dir(slug) / "workspace.json").exists()

    def create_workspace(
        self,
        name: str,
        *,
        slug: str | None = None,
        allowed_domains: list[str] | None = None,
        location_url_pattern: str = "/locations/",
        location_url_min_path_segments: int = 0,
        sitemap_url: str | None = None,
        expected_schema_types: list[str] | None = None,
        business_type: str | None = None,
        question_sets: list[str] | None = None,
        client_config_slug: str | None = None,
    ) -> Workspace:
        slug = slugify(slug or name)
        base = slug
        i = 2
        while self.exists(slug):
            slug = f"{base}-{i}"
            i += 1
        now = utc_now()
        ws = Workspace(
            slug=slug,
            name=name,
            created_at=now,
            updated_at=now,
            allowed_domains=allowed_domains or [],
            location_url_pattern=location_url_pattern,
            location_url_min_path_segments=location_url_min_path_segments,
            sitemap_url=sitemap_url,
            expected_schema_types=expected_schema_types or [],
            business_type=business_type,
            question_sets=question_sets or [],
            client_config_slug=client_config_slug,
        )
        d = self.workspace_dir(slug)
        d.mkdir(parents=True, exist_ok=True)
        (d / "uploads").mkdir(exist_ok=True)
        (d / "jobs").mkdir(exist_ok=True)
        (d / "audits").mkdir(exist_ok=True)
        self._write_json(d / "workspace.json", ws.model_dump(mode="json"))
        self._write_json(d / "locations.json", {"locations": []})
        return ws

    def get_workspace(self, slug: str) -> Workspace:
        path = self.workspace_dir(slug) / "workspace.json"
        if not path.exists():
            raise FileNotFoundError(f"Workspace not found: {slug}")
        return Workspace.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def save_workspace(self, ws: Workspace) -> Workspace:
        ws.updated_at = utc_now()
        self._write_json(self.workspace_dir(ws.slug) / "workspace.json", ws.model_dump(mode="json"))
        return ws

    def load_locations(self, slug: str) -> list[RegisteredLocation]:
        path = self.workspace_dir(slug) / "locations.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return [RegisteredLocation.model_validate(x) for x in data.get("locations", [])]

    def save_locations(self, slug: str, locations: list[RegisteredLocation]) -> None:
        payload = {"locations": [loc.model_dump(mode="json") for loc in locations]}
        self._write_json(self.workspace_dir(slug) / "locations.json", payload)

    def upsert_locations(
        self,
        slug: str,
        incoming: list[RegisteredLocation],
        *,
        source: str,
    ) -> tuple[int, int, list[RegisteredLocation]]:
        """Merge by URL. Returns (added, updated, full list)."""
        existing = {self._norm_url(loc.url): loc for loc in self.load_locations(slug)}
        added = 0
        updated = 0
        for loc in incoming:
            key = self._norm_url(loc.url)
            if not key:
                continue
            if key in existing:
                cur = existing[key]
                for field in (
                    "location_id",
                    "location_name",
                    "city",
                    "region",
                    "postal_code",
                    "phone",
                ):
                    new_val = getattr(loc, field)
                    if new_val and not getattr(cur, field):
                        setattr(cur, field, new_val)
                    elif new_val and source == "csv":
                        setattr(cur, field, new_val)
                if source not in cur.sources:
                    cur.sources.append(source)
                if loc.in_sitemap is not None:
                    cur.in_sitemap = loc.in_sitemap
                if loc.in_csv is not None:
                    cur.in_csv = loc.in_csv
                updated += 1
            else:
                if source not in loc.sources:
                    loc.sources.append(source)
                existing[key] = loc
                added += 1
        merged = list(existing.values())
        merged.sort(key=lambda l: ((l.region or ""), (l.city or ""), (l.location_name or l.url)))
        self.save_locations(slug, merged)
        return added, updated, merged

    def save_job(self, job: AuditJob) -> AuditJob:
        path = self.workspace_dir(job.workspace_slug) / "jobs" / f"{job.job_id}.json"
        self._write_json(path, job.model_dump(mode="json"))
        return job

    def get_job(self, slug: str, job_id: str) -> AuditJob:
        path = self.workspace_dir(slug) / "jobs" / f"{job_id}.json"
        if not path.exists():
            raise FileNotFoundError(job_id)
        return AuditJob.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def latest_job(self, slug: str) -> AuditJob | None:
        ws = self.get_workspace(slug)
        if not ws.last_job_id:
            return None
        try:
            return self.get_job(slug, ws.last_job_id)
        except FileNotFoundError:
            return None

    def save_audit_entities(self, slug: str, entities: list[dict[str, Any]]) -> None:
        path = self.workspace_dir(slug) / "audits" / "latest.json"
        self._write_json(
            path,
            {
                "updated_at": utc_now(),
                "locations": entities,
            },
        )

    def load_audit_entities(self, slug: str) -> list[dict[str, Any]]:
        path = self.workspace_dir(slug) / "audits" / "latest.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("locations") or [])

    def uploads_dir(self, slug: str) -> Path:
        d = self.workspace_dir(slug) / "uploads"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _norm_url(url: str) -> str:
        return (url or "").strip().rstrip("/").lower()

    @staticmethod
    def _write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def new_job_id() -> str:
    return uuid.uuid4().hex[:12]
