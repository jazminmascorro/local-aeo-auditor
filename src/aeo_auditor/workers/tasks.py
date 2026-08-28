"""RQ task entrypoints (imported by worker processes)."""

from __future__ import annotations

import logging

from aeo_auditor.workspaces import WorkspaceStore
from aeo_auditor.workspaces.jobs import run_registry_audit

logger = logging.getLogger(__name__)


def run_registry_audit_task(slug: str, job_id: str) -> dict:
    """Execute a previously created pending audit job."""
    store = WorkspaceStore()
    logger.info("RQ audit start workspace=%s job=%s", slug, job_id)
    job = run_registry_audit(store, slug, job_id)
    result = {
        "job_id": job.job_id,
        "status": job.status,
        "completed": job.completed,
        "total": job.total,
        "error": job.error,
    }
    logger.info("RQ audit finished %s", result)
    return result
