"""End-to-end analysis pipeline."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from aeo_auditor.answers import evaluate_questions
from aeo_auditor.client_config import ClientConfig
from aeo_auditor.crawler import Crawler
from aeo_auditor.entities import LocationNormalizer
from aeo_auditor.models import LocationEntity, PortfolioSummary, RawPageData
from aeo_auditor.parser import raw_from_fetch, raw_from_html
from aeo_auditor.portfolio import aggregate_portfolio
from aeo_auditor.recommendations import generate_recommendations
from aeo_auditor.reporting import export_all
from aeo_auditor.scoring import score_location
from aeo_auditor.sitemap import discover_location_urls

logger = logging.getLogger(__name__)


def analyze_raw(
    raw: RawPageData,
    *,
    client: ClientConfig | None = None,
    in_sitemap: bool | None = None,
) -> LocationEntity:
    normalizer = LocationNormalizer(client)
    entity = normalizer.normalize(raw, in_sitemap=in_sitemap)
    results = evaluate_questions(entity, client=client, visible_text=raw.visible_text)
    entity.answerable_questions = {r.question_id: r for r in results}
    entity.scorecard = score_location(entity, results, client=client)
    recs, strengths, opps, missing, schema_opps = generate_recommendations(entity, results)
    entity.recommendations = recs
    entity.strengths = strengths
    entity.opportunities = opps
    entity.missing_answers = missing
    entity.schema_opportunities = schema_opps
    return entity


def analyze_urls(
    urls: list[str],
    *,
    client: ClientConfig | None = None,
    crawler: Crawler | None = None,
    use_cache: bool = True,
    sitemap_url_set: set[str] | None = None,
    discovered_count: int | None = None,
) -> PortfolioSummary:
    crawler = crawler or Crawler()
    normalizer_client = client
    locations: list[LocationEntity] = []
    fetches = crawler.fetch_many(urls, use_cache=use_cache)
    for fetch in fetches:
        raw = raw_from_fetch(fetch)
        in_sitemap = None
        if sitemap_url_set is not None:
            in_sitemap = fetch.url in sitemap_url_set or (fetch.final_url in sitemap_url_set)
        entity = analyze_raw(raw, client=normalizer_client, in_sitemap=in_sitemap)
        locations.append(entity)
        logger.info(
            "Analyzed %s → score %s",
            entity.url,
            entity.scorecard.total if entity.scorecard else "n/a",
        )
    name = client.client_name if client else "Ad hoc"
    return aggregate_portfolio(name, locations, discovered=discovered_count)


def analyze_html_fixtures(
    pages: list[tuple[str, str]],
    *,
    client: ClientConfig | None = None,
) -> PortfolioSummary:
    locations = []
    for url, html in pages:
        raw = raw_from_html(url, html)
        locations.append(analyze_raw(raw, client=client, in_sitemap=None))
    name = client.client_name if client else "Fixtures"
    return aggregate_portfolio(name, locations)


def resolve_urls_for_run(
    *,
    client: ClientConfig | None = None,
    url: str | None = None,
    urls_file: Path | None = None,
    sitemap: str | None = None,
    use_demo_urls: bool = False,
    limit: int | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Resolve URL list and metadata about discovery."""
    meta: dict[str, Any] = {"sitemap_result": None, "source": None}
    urls: list[str] = []

    if url:
        urls = [url]
        meta["source"] = "single_url"
    elif urls_file:
        urls = [
            line.strip()
            for line in Path(urls_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        meta["source"] = "urls_file"
    elif use_demo_urls and client and client.demo_urls:
        urls = list(client.demo_urls)
        meta["source"] = "demo_urls"
    else:
        sitemap_url = sitemap or (client.location_sitemap if client else None)
        if not sitemap_url:
            if client and client.demo_urls:
                urls = list(client.demo_urls)
                meta["source"] = "demo_urls_fallback"
            else:
                raise ValueError("No URL, urls file, sitemap, or demo URLs provided")
        else:
            result = discover_location_urls(
                sitemap_url,
                pattern=client.location_url_pattern if client else "/locations/",
                allowed_domains=client.allowed_domains if client else None,
                min_path_segments=client.location_url_min_path_segments if client else 0,
                limit=limit,
            )
            meta["sitemap_result"] = {
                "sitemap_url": result.sitemap_url,
                "status_code": result.status_code,
                "empty_body": result.empty_body,
                "error": result.error,
                "urls_found": len(result.urls),
                "location_urls_found": len(result.location_urls),
            }
            urls = list(result.location_urls)
            meta["source"] = "sitemap"
            if not urls and client and client.demo_urls:
                urls = list(client.demo_urls)
                meta["source"] = "demo_urls_fallback_empty_sitemap"
                meta["fallback_reason"] = result.error or "empty or no matching location URLs"

    if limit is not None:
        urls = urls[:limit]
    return urls, meta


def run_analysis(
    *,
    client: ClientConfig | None = None,
    url: str | None = None,
    urls_file: Path | None = None,
    sitemap: str | None = None,
    use_demo_urls: bool = False,
    limit: int | None = None,
    use_cache: bool = True,
    output_dir: Path | None = None,
) -> tuple[PortfolioSummary, dict[str, Any]]:
    urls, meta = resolve_urls_for_run(
        client=client,
        url=url,
        urls_file=urls_file,
        sitemap=sitemap,
        use_demo_urls=use_demo_urls,
        limit=limit,
    )
    if not urls:
        raise ValueError("No location URLs to analyze")

    sitemap_set: set[str] | None = None
    discovered = len(urls)
    if meta.get("sitemap_result"):
        discovered = meta["sitemap_result"].get("location_urls_found") or len(urls)
        # When fallback used, discovered may be 0 from sitemap
        if meta["source"].startswith("demo_urls_fallback"):
            discovered = meta["sitemap_result"].get("location_urls_found", 0)

    portfolio = analyze_urls(
        urls,
        client=client,
        use_cache=use_cache,
        sitemap_url_set=sitemap_set,
        discovered_count=discovered if meta.get("source") == "sitemap" else len(urls),
    )
    meta["export_paths"] = {}
    if output_dir is not None:
        meta["export_paths"] = {k: str(v) for k, v in export_all(portfolio, output_dir).items()}
    return portfolio, meta
