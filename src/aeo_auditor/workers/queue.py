"""RQ queue helpers and audit task."""

from __future__ import annotations

import logging
from typing import Any

from redis import Redis
from rq import Queue
from rq.job import Job

from aeo_auditor.auth.settings import auth_settings

logger = logging.getLogger(__name__)

QUEUE_NAME = "aeo_audits"


def redis_conn() -> Redis:
    return Redis.from_url(auth_settings()["redis_url"])


def get_queue() -> Queue:
    return Queue(QUEUE_NAME, connection=redis_conn())


def redis_available() -> bool:
    try:
        return bool(redis_conn().ping())
    except Exception:  # noqa: BLE001
        return False


def enqueue_audit(slug: str, job_id: str, *, job_timeout: int = 7200) -> dict[str, Any]:
    """Enqueue RQ job. Returns enqueue metadata."""
    q = get_queue()
    rq_job = q.enqueue(
        "aeo_auditor.workers.tasks.run_registry_audit_task",
        slug,
        job_id,
        job_timeout=job_timeout,
        result_ttl=86400,
        failure_ttl=86400,
        meta={"workspace_slug": slug, "audit_job_id": job_id},
    )
    return {"rq_job_id": rq_job.id, "queue": QUEUE_NAME}


def get_rq_job(rq_job_id: str) -> Job | None:
    try:
        return Job.fetch(rq_job_id, connection=redis_conn())
    except Exception:  # noqa: BLE001
        return None
