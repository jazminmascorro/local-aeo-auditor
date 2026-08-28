"""Auth store and RQ enqueue tests."""

from __future__ import annotations

from pathlib import Path

from aeo_auditor.auth.store import AuthStore
from aeo_auditor.workspaces import WorkspaceStore
from aeo_auditor.workspaces.jobs import enqueue_or_run_audit, start_registry_audit
from aeo_auditor.workspaces.ingest import ingest_url_list


def test_auth_membership_flow(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("AUTH_DEV_MODE", "true")
    store = AuthStore(root=tmp_path / "auth")
    user = store.upsert_user(email="a@example.com", name="A", provider="dev")
    assert user.email == "a@example.com"
    store.add_membership("a@example.com", "dutch-bros", role="admin")
    assert store.can_access("a@example.com", "dutch-bros")
    assert not store.can_access("a@example.com", "other")
    assert store.role_for("a@example.com", "dutch-bros") == "admin"


def test_enqueue_or_run_with_redis(tmp_path: Path):
    from aeo_auditor.workers.queue import redis_available

    ws_store = WorkspaceStore(root=tmp_path / "workspaces")
    ws = ws_store.create_workspace("Co", slug="co")
    ingest_url_list(
        ws_store,
        ws,
        ["https://example.com/locations/az/phoenix/1-test"],
        source_label="test",
    )
    # Force sync to avoid needing a live crawl for this unit test of job creation path
    job = start_registry_audit(ws_store, "co", limit=1)
    assert job.status == "pending"
    assert job.total == 1
    assert redis_available() is True
    # enqueue without running worker — job stays pending/queued message
    from aeo_auditor.workers.queue import enqueue_audit

    meta = enqueue_audit("co", job.job_id)
    assert "rq_job_id" in meta
