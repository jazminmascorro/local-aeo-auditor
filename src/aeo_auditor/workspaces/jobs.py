"""Audit jobs over a workspace location registry."""

from __future__ import annotations

import logging
from typing import Any

from aeo_auditor.client_config import ClientConfig
from aeo_auditor.crawler import Crawler
from aeo_auditor.pipeline import analyze_raw
from aeo_auditor.parser import raw_from_fetch
from aeo_auditor.portfolio import aggregate_portfolio
from aeo_auditor.reporting import export_all
from aeo_auditor.paths import project_path
from aeo_auditor.workspaces import AuditJob, WorkspaceStore, new_job_id, utc_now

logger = logging.getLogger(__name__)


def client_config_for_workspace(store: WorkspaceStore, slug: str) -> ClientConfig | None:
    ws = store.get_workspace(slug)
    if ws.client_config_slug:
        try:
            return ClientConfig.load(ws.client_config_slug)
        except FileNotFoundError:
            pass
    # synthesize lightweight client config from workspace
    return ClientConfig(
        client_name=ws.name,
        client_slug=ws.slug,
        location_sitemap=ws.sitemap_url,
        allowed_domains=ws.allowed_domains,
        location_url_pattern=ws.location_url_pattern,
        location_url_min_path_segments=ws.location_url_min_path_segments,
        expected_schema_types=ws.expected_schema_types,
        business_type=ws.business_type,
        question_sets=ws.question_sets,
    )


def start_registry_audit(
    store: WorkspaceStore,
    slug: str,
    *,
    limit: int | None = None,
    use_cache: bool = True,
    only_unaudited: bool = False,
) -> AuditJob:
    ws = store.get_workspace(slug)
    locations = store.load_locations(slug)
    if only_unaudited:
        locations = [loc for loc in locations if loc.last_audited_at is None]
    if limit is not None:
        locations = locations[:limit]
    job = AuditJob(
        job_id=new_job_id(),
        workspace_slug=slug,
        status="pending",
        created_at=utc_now(),
        total=len(locations),
        completed=0,
        limit=limit,
        use_cache=use_cache,
        message=f"Queued {len(locations)} locations",
    )
    store.save_job(job)
    ws.last_job_id = job.job_id
    store.save_workspace(ws)
    return job


def run_registry_audit(store: WorkspaceStore, slug: str, job_id: str) -> AuditJob:
    job = store.get_job(slug, job_id)
    ws = store.get_workspace(slug)
    job.status = "running"
    job.started_at = utc_now()
    job.message = "Running"
    store.save_job(job)

    try:
        registry = store.load_locations(slug)
        targets = list(registry)
        if job.limit is not None:
            # Prefer unaudited first when limiting
            unaudited = [r for r in targets if r.last_audited_at is None]
            audited = [r for r in targets if r.last_audited_at is not None]
            ordered = unaudited + audited
            targets = ordered[: job.limit]
        job.total = len(targets)
        store.save_job(job)

        client = client_config_for_workspace(store, slug)
        crawler = Crawler()
        sitemap_urls = {r.url for r in registry if r.in_sitemap}
        entities = []
        by_url = {store._norm_url(r.url): r for r in registry}

        for i, reg in enumerate(targets, start=1):
            fetch = crawler.fetch(reg.url, use_cache=job.use_cache)
            raw = raw_from_fetch(fetch)
            in_sitemap = reg.in_sitemap
            if in_sitemap is None and sitemap_urls:
                in_sitemap = reg.url in sitemap_urls
            entity = analyze_raw(raw, client=client, in_sitemap=in_sitemap)
            # enrich from registry if page missing fields
            if not entity.location_id and reg.location_id:
                entity.location_id = reg.location_id
            if not entity.location_name and reg.location_name:
                entity.location_name = reg.location_name
            if not entity.address.city and reg.city:
                entity.address.city = reg.city
            if not entity.address.region and reg.region:
                entity.address.region = reg.region
            if not entity.phone and reg.phone:
                entity.phone = reg.phone

            entities.append(entity)
            key = store._norm_url(reg.url)
            if key in by_url:
                row = by_url[key]
                row.last_audited_at = utc_now()
                if entity.scorecard:
                    row.aeo_score = entity.scorecard.total
                    row.band = entity.scorecard.band
                    row.discovery = entity.scorecard.discovery.score
                    row.entity_clarity = entity.scorecard.entity_clarity.score
                    row.structured_data = entity.scorecard.structured_data.score
                    row.answer_coverage = entity.scorecard.answer_coverage.score
                    row.local_uniqueness = entity.scorecard.local_uniqueness.score
                row.issues_count = len(entity.conflicts) + len(entity.opportunities)
                if entity.location_name:
                    row.location_name = entity.location_name
                if entity.address.city:
                    row.city = entity.address.city
                if entity.address.region:
                    row.region = entity.address.region
                if entity.location_id:
                    row.location_id = entity.location_id
            job.completed = i
            job.message = f"Audited {i}/{job.total}"
            store.save_job(job)
            # persist registry incrementally
            store.save_locations(slug, list(by_url.values()))

        portfolio = aggregate_portfolio(ws.name, entities, discovered=len(registry))
        # Merge with prior audit details so earlier locations remain viewable
        prior = {store._norm_url(e.get("url", "")): e for e in store.load_audit_entities(slug)}
        for entity in entities:
            prior[store._norm_url(entity.url)] = entity.model_dump(mode="json")
        store.save_audit_entities(slug, list(prior.values()))
        # keep full latest as this run's entities; registry holds scores for all ever audited
        ws.portfolio_summary = {
            "client": portfolio.client,
            "locations_discovered": len(registry),
            "locations_crawled": sum(1 for r in by_url.values() if r.last_audited_at),
            "average_aeo_score": _avg([r.aeo_score for r in by_url.values() if r.aeo_score is not None]),
            "category_averages": portfolio.category_averages,
            "score_distribution": portfolio.score_distribution,
            "systemic_opportunities": portfolio.systemic_opportunities,
            "cross_location_stats": portfolio.cross_location_stats,
            "last_run_count": len(entities),
        }
        # recompute distribution from registry scores
        registry_after = list(by_url.values())
        ws.portfolio_summary["score_distribution"] = _distribution(
            [r.aeo_score for r in registry_after if r.aeo_score is not None]
        )
        ws.portfolio_summary["category_averages"] = _category_avgs(registry_after)
        ws.last_audit_at = utc_now()
        store.save_workspace(ws)

        # also export to workspace audits + shared output
        export_dir = store.workspace_dir(slug) / "audits" / "exports"
        export_all(portfolio, export_dir)
        export_all(portfolio, project_path("output"))

        job.status = "completed"
        job.finished_at = utc_now()
        job.message = f"Completed {job.completed}/{job.total}"
        store.save_job(job)
        return job
    except Exception as exc:  # noqa: BLE001
        logger.exception("Audit job failed")
        job.status = "failed"
        job.error = str(exc)
        job.message = "Failed"
        job.finished_at = utc_now()
        store.save_job(job)
        return job


def run_audit_now(
    store: WorkspaceStore,
    slug: str,
    *,
    limit: int | None = None,
    use_cache: bool = True,
) -> AuditJob:
    job = start_registry_audit(store, slug, limit=limit, use_cache=use_cache)
    return run_registry_audit(store, slug, job.job_id)


def _avg(values: list[float | None]) -> float:
    nums = [v for v in values if v is not None]
    return round(sum(nums) / len(nums), 1) if nums else 0.0


def _distribution(scores: list[float]) -> dict[str, int]:
    bands = {"Excellent": 0, "Strong": 0, "Good": 0, "Needs improvement": 0, "Weak": 0}
    for s in scores:
        if s >= 90:
            bands["Excellent"] += 1
        elif s >= 80:
            bands["Strong"] += 1
        elif s >= 70:
            bands["Good"] += 1
        elif s >= 60:
            bands["Needs improvement"] += 1
        else:
            bands["Weak"] += 1
    return {k: v for k, v in bands.items() if v}


def _category_avgs(registry: list[Any]) -> dict[str, float]:
    def pct(vals: list[float | None]) -> float:
        nums = [v for v in vals if v is not None]
        return round((sum(nums) / len(nums) / 20.0) * 100, 1) if nums else 0.0

    return {
        "discovery": pct([r.discovery for r in registry]),
        "entity_clarity": pct([r.entity_clarity for r in registry]),
        "structured_data": pct([r.structured_data for r in registry]),
        "answer_coverage": pct([r.answer_coverage for r in registry]),
        "local_uniqueness": pct([r.local_uniqueness for r in registry]),
    }
