"""Auth helpers for FastAPI request/session."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from starlette.responses import RedirectResponse

from aeo_auditor.auth.settings import auth_settings
from aeo_auditor.auth.store import AuthStore, User


def get_auth_store() -> AuthStore:
    return AuthStore()


def current_user(request: Request) -> User | None:
    email = request.session.get("user_email")
    if not email:
        return None
    return get_auth_store().get_user(email)


def require_user(request: Request) -> User:
    user = current_user(request)
    if user:
        return user
    raise HTTPException(status_code=401, detail="Authentication required")


def login_redirect(next_url: str = "/") -> RedirectResponse:
    return RedirectResponse(f"/auth/login?next={next_url}", status_code=303)


def require_workspace_access(request: Request, slug: str) -> User:
    user = require_user(request)
    store = get_auth_store()
    if not store.can_access(user.email, slug):
        raise HTTPException(status_code=403, detail="No access to this workspace")
    return user


def session_user_payload(user: User) -> dict[str, Any]:
    return {
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "provider": user.provider,
    }


def complete_login(
    request: Request,
    *,
    email: str,
    name: str | None,
    picture: str | None,
    provider: str,
) -> User:
    settings = auth_settings()
    store = get_auth_store()
    user = store.upsert_user(email=email, name=name, picture=picture, provider=provider)
    # Auto-join configured demo workspace on first login if they have no memberships
    if not store.list_memberships(user.email) and settings.get("auto_join_workspace"):
        store.ensure_auto_join(user.email, settings["auto_join_workspace"])
    request.session["user_email"] = user.email
    request.session["user_name"] = user.name or user.email
    return user
