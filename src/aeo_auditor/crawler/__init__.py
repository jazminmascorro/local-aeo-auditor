"""Safe cached HTTP crawler."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from aeo_auditor.paths import load_yaml, project_path

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    content: str
    headers: dict[str, str]
    redirect_chain: list[str]
    from_cache: bool = False
    error: str | None = None


def default_crawl_config() -> dict[str, Any]:
    path = project_path("config", "crawl.yaml")
    if path.exists():
        return load_yaml(path)
    return {
        "user_agent": "LocationAnswerabilityAuditor/0.1",
        "delay_seconds": 1.0,
        "concurrency": 2,
        "timeout_seconds": 30,
        "max_retries": 3,
        "retry_backoff_seconds": 2.0,
        "cache_dir": ".cache/pages",
        "cache_enabled": True,
        "follow_redirects": True,
        "max_redirects": 5,
        "resume_journal": ".cache/completed_urls.json",
    }


class PageCache:
    def __init__(self, cache_dir: Path, enabled: bool = True) -> None:
        self.cache_dir = cache_dir
        self.enabled = enabled
        if enabled:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def path_for(self, url: str) -> Path:
        return self.cache_dir / f"{self.key(url)}.json"

    def get(self, url: str) -> FetchResult | None:
        if not self.enabled:
            return None
        path = self.path_for(url)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return FetchResult(
                url=data["url"],
                final_url=data.get("final_url", data["url"]),
                status_code=data["status_code"],
                content=data.get("content", ""),
                headers=data.get("headers", {}),
                redirect_chain=data.get("redirect_chain", []),
                from_cache=True,
            )
        except (json.JSONDecodeError, KeyError, OSError) as exc:
            logger.warning("Cache read failed for %s: %s", url, exc)
            return None

    def put(self, result: FetchResult) -> None:
        if not self.enabled:
            return
        path = self.path_for(result.url)
        payload = {
            "url": result.url,
            "final_url": result.final_url,
            "status_code": result.status_code,
            "content": result.content,
            "headers": result.headers,
            "redirect_chain": result.redirect_chain,
        }
        path.write_text(json.dumps(payload), encoding="utf-8")


class ResumeJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._done: set[str] = set()
        if self.path.exists():
            try:
                self._done = set(json.loads(self.path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                self._done = set()

    def contains(self, url: str) -> bool:
        return url in self._done

    def mark(self, url: str) -> None:
        self._done.add(url)
        self.path.write_text(json.dumps(sorted(self._done)), encoding="utf-8")


class Crawler:
    def __init__(self, config: dict[str, Any] | None = None, root: Path | None = None) -> None:
        self.config = {**default_crawl_config(), **(config or {})}
        root = root or project_path()
        cache_dir = root / self.config.get("cache_dir", ".cache/pages")
        self.cache = PageCache(cache_dir, enabled=bool(self.config.get("cache_enabled", True)))
        journal_path = root / self.config.get("resume_journal", ".cache/completed_urls.json")
        self.journal = ResumeJournal(journal_path)
        self._last_request_at = 0.0
        self.user_agent = self.config.get(
            "user_agent",
            "LocationAnswerabilityAuditor/0.1",
        )

    def _throttle(self) -> None:
        delay = float(self.config.get("delay_seconds", 1.0))
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < delay:
            time.sleep(delay - elapsed)

    def fetch(self, url: str, *, use_cache: bool = True) -> FetchResult:
        if use_cache:
            cached = self.cache.get(url)
            if cached is not None:
                return cached

        timeout = float(self.config.get("timeout_seconds", 30))
        retries = int(self.config.get("max_retries", 3))
        backoff = float(self.config.get("retry_backoff_seconds", 2.0))
        last_error: str | None = None

        for attempt in range(retries):
            self._throttle()
            try:
                with httpx.Client(
                    headers={
                        "User-Agent": self.user_agent,
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    },
                    timeout=timeout,
                    follow_redirects=bool(self.config.get("follow_redirects", True)),
                    max_redirects=int(self.config.get("max_redirects", 5)),
                ) as client:
                    self._last_request_at = time.monotonic()
                    resp = client.get(url)
                    redirect_chain = [str(r.url) for r in resp.history]
                    result = FetchResult(
                        url=url,
                        final_url=str(resp.url),
                        status_code=resp.status_code,
                        content=resp.text,
                        headers={k: v for k, v in resp.headers.items()},
                        redirect_chain=redirect_chain,
                        from_cache=False,
                    )
                    self.cache.put(result)
                    return result
            except httpx.HTTPError as exc:
                last_error = str(exc)
                logger.warning("Fetch attempt %s failed for %s: %s", attempt + 1, url, exc)
                time.sleep(backoff * (attempt + 1))

        return FetchResult(
            url=url,
            final_url=url,
            status_code=0,
            content="",
            headers={},
            redirect_chain=[],
            error=last_error or "Unknown fetch error",
        )

    def fetch_many(
        self,
        urls: list[str],
        *,
        use_cache: bool = True,
        skip_completed: bool = False,
        limit: int | None = None,
    ) -> list[FetchResult]:
        selected = urls[:limit] if limit is not None else list(urls)
        results: list[FetchResult] = []
        for url in selected:
            if skip_completed and self.journal.contains(url):
                cached = self.cache.get(url)
                if cached:
                    results.append(cached)
                    continue
            result = self.fetch(url, use_cache=use_cache)
            results.append(result)
            if result.error is None and result.status_code:
                self.journal.mark(url)
        return results


def is_allowed_domain(url: str, allowed_domains: list[str]) -> bool:
    if not allowed_domains:
        return True
    host = (urlparse(url).hostname or "").lower()
    for domain in allowed_domains:
        d = domain.lower()
        if host == d or host.endswith("." + d.lstrip("www.")) or host == d.lstrip("www."):
            return True
        if host.endswith(d):
            return True
    return False
