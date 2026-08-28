"""Raw HTML extraction into RawPageData."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from aeo_auditor.crawler import FetchResult
from aeo_auditor.models import (
    BreadcrumbItem,
    FAQItem,
    OpenGraphData,
    RawPageData,
)


def _meta_content(soup: BeautifulSoup, **attrs: str) -> str | None:
    tag = soup.find("meta", attrs=attrs)
    if tag and tag.get("content"):
        return str(tag["content"]).strip()
    return None


def _text(el: Tag | None) -> str:
    if el is None:
        return ""
    return " ".join(el.get_text(" ", strip=True).split())


def extract_json_ld(soup: BeautifulSoup) -> tuple[list[Any], list[str], list[str]]:
    blocks: list[Any] = []
    raw_blocks: list[str] = []
    errors: list[str] = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = script.string or script.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        raw_blocks.append(raw)
        try:
            blocks.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            errors.append(str(exc))
            # try to salvage trailing commas lightly
            try:
                cleaned = re.sub(r",\s*}", "}", raw)
                cleaned = re.sub(r",\s*]", "]", cleaned)
                blocks.append(json.loads(cleaned))
                errors.pop()
            except json.JSONDecodeError:
                pass
    return blocks, raw_blocks, errors


def extract_breadcrumbs(soup: BeautifulSoup, base_url: str) -> list[BreadcrumbItem]:
    items: list[BreadcrumbItem] = []
    nav = soup.find("nav", attrs={"aria-label": re.compile(r"breadcrumb", re.I)})
    if not nav:
        nav = soup.find(attrs={"itemtype": re.compile(r"BreadcrumbList", re.I)})
    if not nav:
        return items
    for i, li in enumerate(nav.find_all("li"), start=1):
        name_el = li.find(attrs={"itemprop": "name"}) or li.find("a") or li
        link = li.find("a")
        url = urljoin(base_url, link["href"]) if link and link.get("href") else None
        name = _text(name_el)
        if name:
            items.append(BreadcrumbItem(name=name, url=url, position=i))
    return items


def extract_faqs(soup: BeautifulSoup) -> list[FAQItem]:
    faqs: list[FAQItem] = []
    # FAQPage schema handled elsewhere; visible patterns
    for details in soup.find_all("details"):
        summary = details.find("summary")
        if summary:
            q = _text(summary)
            a = _text(details)
            if q and a:
                faqs.append(FAQItem(question=q, answer=a.replace(q, "", 1).strip()))
    # dt/dd
    for dl in soup.find_all("dl"):
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            q, a = _text(dt), _text(dd)
            if q and a:
                faqs.append(FAQItem(question=q, answer=a))
    # headings followed by paragraph with "?" in heading
    for heading in soup.find_all(re.compile(r"^h[2-4]$")):
        q = _text(heading)
        if "?" not in q:
            continue
        sibling = heading.find_next_sibling()
        if sibling:
            a = _text(sibling)
            if a:
                faqs.append(FAQItem(question=q, answer=a))
    return faqs


def extract_visible_text(soup: BeautifulSoup) -> str:
    clone = BeautifulSoup(str(soup), "lxml")
    for tag in clone(["script", "style", "noscript", "svg", "template"]):
        tag.decompose()
    text = clone.get_text("\n", strip=True)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def extract_links(soup: BeautifulSoup, base_url: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = str(a["href"]).strip()
        if href.startswith("#") or href.startswith("javascript:"):
            continue
        links.append({"href": urljoin(base_url, href), "text": _text(a)})
    return links


def extract_open_graph(soup: BeautifulSoup) -> OpenGraphData:
    def og(prop: str) -> str | None:
        return _meta_content(soup, property=prop) or _meta_content(soup, name=prop)

    return OpenGraphData(
        title=og("og:title"),
        description=og("og:description"),
        url=og("og:url"),
        image=og("og:image"),
        type=og("og:type"),
        site_name=og("og:site_name"),
    )


def raw_from_fetch(fetch: FetchResult) -> RawPageData:
    if fetch.error and not fetch.content:
        return RawPageData(
            url=fetch.url,
            final_url=fetch.final_url,
            status_code=fetch.status_code,
            redirect_chain=fetch.redirect_chain,
            error=fetch.error,
            fetched_from_cache=fetch.from_cache,
            headers=fetch.headers,
        )

    soup = BeautifulSoup(fetch.content or "", "lxml")
    canonical_tag = soup.find("link", rel=lambda v: v and "canonical" in str(v).lower())
    canonical = None
    if canonical_tag and canonical_tag.get("href"):
        canonical = urljoin(fetch.final_url, str(canonical_tag["href"]))

    robots = _meta_content(soup, name="robots") or _meta_content(soup, name="googlebot")
    title_tag = soup.find("title")
    h1s = [_text(h) for h in soup.find_all("h1") if _text(h)]
    headings = []
    for level in range(1, 7):
        for h in soup.find_all(f"h{level}"):
            t = _text(h)
            if t:
                headings.append({"level": f"h{level}", "text": t})

    json_ld, json_ld_raw, json_ld_errors = extract_json_ld(soup)
    base = fetch.final_url or fetch.url

    return RawPageData(
        url=fetch.url,
        final_url=fetch.final_url,
        status_code=fetch.status_code,
        redirect_chain=fetch.redirect_chain,
        canonical=canonical,
        robots_meta=robots,
        title=_text(title_tag) if title_tag else None,
        meta_description=_meta_content(soup, name="description"),
        h1=h1s,
        headings=headings,
        visible_text=extract_visible_text(soup),
        links=extract_links(soup, base),
        breadcrumbs=extract_breadcrumbs(soup, base),
        faqs=extract_faqs(soup),
        json_ld_blocks=json_ld,
        json_ld_raw=json_ld_raw,
        json_ld_errors=json_ld_errors,
        open_graph=extract_open_graph(soup),
        html_excerpt=(fetch.content or "")[:5000] if fetch.content else None,
        fetched_from_cache=fetch.from_cache,
        error=fetch.error,
        headers=fetch.headers,
    )


def raw_from_html(url: str, html: str, status_code: int = 200) -> RawPageData:
    fetch = FetchResult(
        url=url,
        final_url=url,
        status_code=status_code,
        content=html,
        headers={},
        redirect_chain=[],
        from_cache=False,
    )
    return raw_from_fetch(fetch)
