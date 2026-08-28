"""Client configuration loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aeo_auditor.paths import load_yaml, project_path


@dataclass
class ClientConfig:
    client_name: str
    client_slug: str
    location_sitemap: str | None = None
    allowed_domains: list[str] = field(default_factory=list)
    location_url_pattern: str = "/locations/"
    location_url_min_path_segments: int = 0
    expected_schema_types: list[str] = field(default_factory=list)
    business_type: str | None = None
    question_sets: list[str] = field(default_factory=list)
    demo_urls: list[str] = field(default_factory=list)
    extraction_hints: dict[str, Any] = field(default_factory=dict)
    root: Path | None = None

    @classmethod
    def load(cls, client_slug: str | None = None, config_path: Path | None = None) -> ClientConfig | None:
        if config_path is None and client_slug is None:
            return None
        if config_path is None:
            config_path = project_path("clients", client_slug, "config.yaml")  # type: ignore[arg-type]
        if not config_path.exists():
            raise FileNotFoundError(f"Client config not found: {config_path}")
        data = load_yaml(config_path)
        root = config_path.parent
        demo_urls: list[str] = []
        demo_file = data.get("demo_urls_file")
        if demo_file:
            demo_path = root / demo_file
            if demo_path.exists():
                demo_urls = [
                    line.strip()
                    for line in demo_path.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.strip().startswith("#")
                ]
        return cls(
            client_name=data.get("client_name", client_slug or "Unknown"),
            client_slug=data.get("client_slug", client_slug or root.name),
            location_sitemap=data.get("location_sitemap"),
            allowed_domains=list(data.get("allowed_domains") or []),
            location_url_pattern=data.get("location_url_pattern", "/locations/"),
            location_url_min_path_segments=int(data.get("location_url_min_path_segments") or 0),
            expected_schema_types=list(data.get("expected_schema_types") or []),
            business_type=data.get("business_type"),
            question_sets=list(data.get("question_sets") or []),
            demo_urls=demo_urls,
            extraction_hints=dict(data.get("extraction_hints") or {}),
            root=root,
        )


def list_clients() -> list[str]:
    clients_dir = project_path("clients")
    if not clients_dir.exists():
        return []
    return sorted(p.name for p in clients_dir.iterdir() if p.is_dir() and (p / "config.yaml").exists())
