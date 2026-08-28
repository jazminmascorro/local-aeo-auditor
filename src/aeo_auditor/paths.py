"""Shared path helpers and config loading."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

# Package root: src/aeo_auditor
PACKAGE_ROOT = Path(__file__).resolve().parent
# Repo root (when installed editable / running from source)
REPO_ROOT = PACKAGE_ROOT.parents[1]


def find_repo_root() -> Path:
    """Locate repo root by walking up for pyproject.toml / config/."""
    candidates = [REPO_ROOT, Path.cwd(), *Path.cwd().parents]
    for path in candidates:
        if (path / "pyproject.toml").exists() or (path / "config").is_dir():
            return path
    return Path.cwd()


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}")
    return data


def project_path(*parts: str) -> Path:
    return find_repo_root().joinpath(*parts)


def env_or(key: str, default: str) -> str:
    return os.environ.get(key, default)
