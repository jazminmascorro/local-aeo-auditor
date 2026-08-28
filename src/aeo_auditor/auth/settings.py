"""Auth settings from environment."""

from __future__ import annotations

import os
from functools import lru_cache


@lru_cache
def auth_settings() -> dict:
    google_client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    google_client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    secret = os.environ.get("SESSION_SECRET", "").strip() or "dev-insecure-change-me"
    redis_url = os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0").strip()
    base_url = os.environ.get("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    dev_mode = os.environ.get("AUTH_DEV_MODE", "").lower() in {"1", "true", "yes"}
    if not google_client_id or not google_client_secret:
        # Allow local demo login when Google is not configured
        dev_mode = True
    auto_join = os.environ.get("AUTH_AUTO_JOIN_WORKSPACE", "dutch-bros").strip()
    return {
        "google_client_id": google_client_id,
        "google_client_secret": google_client_secret,
        "google_enabled": bool(google_client_id and google_client_secret),
        "session_secret": secret,
        "redis_url": redis_url,
        "base_url": base_url,
        "dev_mode": dev_mode,
        "auto_join_workspace": auto_join or None,
        "session_https_only": os.environ.get("SESSION_HTTPS_ONLY", "").lower() in {"1", "true", "yes"},
    }
