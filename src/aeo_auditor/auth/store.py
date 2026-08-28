"""File-backed users and workspace memberships (MVP; swap for DB later)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from aeo_auditor.paths import project_path
from aeo_auditor.workspaces import utc_now

Role = Literal["admin", "analyst", "viewer"]


class User(BaseModel):
    email: str
    name: str | None = None
    picture: str | None = None
    provider: str = "google"
    created_at: str
    last_login_at: str


class Membership(BaseModel):
    email: str
    workspace_slug: str
    role: Role = "analyst"
    created_at: str


class AuthStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or project_path("data", "auth")
        self.root.mkdir(parents=True, exist_ok=True)
        self.users_path = self.root / "users.json"
        self.memberships_path = self.root / "memberships.json"
        if not self.users_path.exists():
            self._write(self.users_path, {"users": []})
        if not self.memberships_path.exists():
            self._write(self.memberships_path, {"memberships": []})

    def upsert_user(
        self,
        *,
        email: str,
        name: str | None = None,
        picture: str | None = None,
        provider: str = "google",
    ) -> User:
        email = email.strip().lower()
        users = self.list_users()
        now = utc_now()
        for i, user in enumerate(users):
            if user.email == email:
                user.name = name or user.name
                user.picture = picture or user.picture
                user.provider = provider
                user.last_login_at = now
                users[i] = user
                self._save_users(users)
                return user
        user = User(
            email=email,
            name=name,
            picture=picture,
            provider=provider,
            created_at=now,
            last_login_at=now,
        )
        users.append(user)
        self._save_users(users)
        return user

    def get_user(self, email: str) -> User | None:
        email = email.strip().lower()
        return next((u for u in self.list_users() if u.email == email), None)

    def list_users(self) -> list[User]:
        data = json.loads(self.users_path.read_text(encoding="utf-8"))
        return [User.model_validate(u) for u in data.get("users", [])]

    def list_memberships(self, email: str | None = None) -> list[Membership]:
        data = json.loads(self.memberships_path.read_text(encoding="utf-8"))
        items = [Membership.model_validate(m) for m in data.get("memberships", [])]
        if email:
            email = email.strip().lower()
            items = [m for m in items if m.email == email]
        return items

    def get_membership(self, email: str, workspace_slug: str) -> Membership | None:
        email = email.strip().lower()
        for m in self.list_memberships(email):
            if m.workspace_slug == workspace_slug:
                return m
        return None

    def add_membership(self, email: str, workspace_slug: str, role: Role = "analyst") -> Membership:
        email = email.strip().lower()
        existing = self.get_membership(email, workspace_slug)
        if existing:
            return existing
        memberships = self.list_memberships()
        m = Membership(email=email, workspace_slug=workspace_slug, role=role, created_at=utc_now())
        memberships.append(m)
        self._write(self.memberships_path, {"memberships": [x.model_dump(mode="json") for x in memberships]})
        return m

    def workspace_slugs_for(self, email: str) -> list[str]:
        return [m.workspace_slug for m in self.list_memberships(email)]

    def can_access(self, email: str, workspace_slug: str) -> bool:
        return self.get_membership(email, workspace_slug) is not None

    def role_for(self, email: str, workspace_slug: str) -> Role | None:
        m = self.get_membership(email, workspace_slug)
        return m.role if m else None

    def ensure_auto_join(self, email: str, workspace_slug: str | None) -> None:
        if not workspace_slug:
            return
        # Only auto-join if workspace exists on disk
        from aeo_auditor.workspaces import WorkspaceStore

        if WorkspaceStore().exists(workspace_slug):
            self.add_membership(email, workspace_slug, role="admin")

    def _save_users(self, users: list[User]) -> None:
        self._write(self.users_path, {"users": [u.model_dump(mode="json") for u in users]})

    @staticmethod
    def _write(path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
