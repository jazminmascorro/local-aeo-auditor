"""Sitemap discovery: urlset and sitemap index support."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


@dataclass
class SitemapResult:
    sitemap_url: str
    status_code: int | None = None
    urls: list[str] = field(default_factory=list)
    child_sitemaps: list[str] = field(default_factory=list)
    empty_body: bool = False
    error: str | None = None
    location_urls: list[str] = field(default_factory=list)


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _extract_locs(root: ET.Element) -> tuple[list[str], list[str]]:
    urls: list[str] = []
    sitemaps: list[str] = []
    for el in root.iter():
        if _local(el.tag) == "loc" and el.text:
            loc = el.text.strip()
            parent = _local(el.getparent().tag) if hasattr(el, "getparent") and el.getparent() is not None else ""
            # ElementTree doesn't have getparent; classify by ancestor walk via structure
            urls.append(loc)
    # Re-parse with structure awareness
    urls = []
    sitemaps = []
    for child in list(root):
        name = _local(child.tag)
        if name == "sitemap":
            for sub in child:
                if _local(sub.tag) == "loc" and sub.text:
                    sitemaps.append(sub.text.strip())
        elif name == "url":
            for sub in child:
                if _local(sub.tag) == "loc" and sub.text:
                    urls.append(sub.text.strip())
        elif name == "loc" and child.text:
            urls.append(child.text.strip())
    # Fallback: any loc
    if not urls and not sitemaps:
        for el in root.iter():
            if _local(el.tag) == "loc" and el.text:
                urls.append(el.text.strip())
    return urls, sitemaps


def filter_location_urls(
    urls: list[str],
    pattern: str = "/locations/",
    allowed_domains: list[str] | None = None,
    min_path_segments: int = 0,
) -> list[str]:
    out: list[str] = []
    allowed = {d.lower().lstrip("www.") for d in (allowed_domains or [])}
    for url in urls:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().lstrip("www.")
        if allowed and host not in allowed and (parsed.hostname or "").lower() not in {
            d.lower() for d in (allowed_domains or [])
        }:
            # also allow exact domain match including www
            if allowed_domains and not any(
                (parsed.hostname or "").lower().endswith(d.lower().lstrip("www."))
                or (parsed.hostname or "").lower() == d.lower()
                for d in allowed_domains
            ):
                continue
        if pattern and pattern not in parsed.path:
            continue
        segments = [s for s in parsed.path.split("/") if s]
        # path like /locations/az/phoenix/street → after pattern, count segments after 'locations'
        if min_path_segments > 0:
            try:
                idx = segments.index(pattern.strip("/").split("/")[0]) if pattern.strip("/") else 0
                after = segments[idx + 1 :]
            except ValueError:
                after = segments
            if len(after) < min_path_segments:
                continue
        out.append(url)
    # dedupe preserve order
    seen: set[str] = set()
    deduped: list[str] = []
    for u in out:
        if u not in seen:
            seen.add(u)
            deduped.append(u)
    return deduped


def parse_sitemap_xml(content: str, sitemap_url: str) -> SitemapResult:
    result = SitemapResult(sitemap_url=sitemap_url)
    text = (content or "").strip()
    if not text:
        result.empty_body = True
        result.error = "Sitemap response body was empty"
        return result
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        result.error = f"Malformed sitemap XML: {exc}"
        return result
    urls, children = _extract_locs(root)
    result.urls = urls
    result.child_sitemaps = children
    return result


def fetch_sitemap(
    sitemap_url: str,
    *,
    client: httpx.Client | None = None,
    user_agent: str = "LocationAnswerabilityAuditor/0.1",
    timeout: float = 30.0,
    max_child_sitemaps: int = 20,
) -> SitemapResult:
    owns = client is None
    http = client or httpx.Client(
        headers={"User-Agent": user_agent, "Accept": "application/xml,text/xml,*/*"},
        timeout=timeout,
        follow_redirects=True,
    )
    try:
        resp = http.get(sitemap_url)
        result = parse_sitemap_xml(resp.text, sitemap_url)
        result.status_code = resp.status_code
        if result.empty_body or result.error:
            return result
        # Expand sitemap indexes (bounded)
        all_urls = list(result.urls)
        for child in result.child_sitemaps[:max_child_sitemaps]:
            try:
                child_resp = http.get(child)
                child_result = parse_sitemap_xml(child_resp.text, child)
                all_urls.extend(child_result.urls)
            except httpx.HTTPError as exc:
                logger.warning("Failed to fetch child sitemap %s: %s", child, exc)
        result.urls = all_urls
        return result
    except httpx.HTTPError as exc:
        return SitemapResult(sitemap_url=sitemap_url, error=str(exc))
    finally:
        if owns:
            http.close()


def discover_location_urls(
    sitemap_url: str,
    *,
    pattern: str = "/locations/",
    allowed_domains: list[str] | None = None,
    min_path_segments: int = 0,
    limit: int | None = None,
    client: httpx.Client | None = None,
    user_agent: str = "LocationAnswerabilityAuditor/0.1",
) -> SitemapResult:
    result = fetch_sitemap(sitemap_url, client=client, user_agent=user_agent)
    result.location_urls = filter_location_urls(
        result.urls,
        pattern=pattern,
        allowed_domains=allowed_domains,
        min_path_segments=min_path_segments,
    )
    if limit is not None:
        result.location_urls = result.location_urls[:limit]
    return result
