"""Single-page fetch.

The real bounded worker pool arrives in Milestone 3; this is one honest ``async``
GET that proves the fetch path end to end. It enforces the crawl safety rules on
*every* redirect hop, not just the first URL — a redirect can cross to a host
that is off the allowlist or disallowed by robots, and checking only the entry
URL would be a real hole.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

import aiohttp

from minisearch.config import Config
from minisearch.robots.cache import RobotsCache
from minisearch.urls import canonicalize

# Redirect statuses we follow manually so we can re-check each hop.
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MAX_REDIRECTS = 5
_READ_CHUNK = 8192


class FetchError(Exception):
    """A fetch failed (network error, too large, too many redirects)."""


class DisallowedError(FetchError):
    """The URL is off the allowlist or blocked by robots.txt."""


@dataclass
class FetchResult:
    url: str            # final canonical URL after any redirects
    status: int
    content_type: str   # e.g. "text/html" (parameters stripped)
    body: str


async def fetch_page(
    url: str,
    config: Config,
    session: aiohttp.ClientSession,
    robots: RobotsCache | None = None,
) -> FetchResult:
    """Fetch a single URL, following redirects with per-hop safety checks."""
    current = canonicalize(url)
    timeout = aiohttp.ClientTimeout(total=config.request_timeout_s)
    headers = {"User-Agent": config.user_agent}

    for _ in range(_MAX_REDIRECTS + 1):
        parts = urlsplit(current)

        # Safety rail 1: hard allowlist. host==None (malformed) is never allowed.
        if not config.is_host_allowed(parts.hostname or ""):
            raise DisallowedError(f"host not on allowlist: {current}")

        # Safety rail 2: robots.txt for this host.
        if robots is not None:
            rules = await robots.get(parts.scheme, parts.netloc)
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query
            if not rules.can_fetch(path):
                raise DisallowedError(f"blocked by robots.txt: {current}")

        try:
            async with session.get(
                current, headers=headers, timeout=timeout, allow_redirects=False
            ) as resp:
                if resp.status in _REDIRECT_STATUSES and "Location" in resp.headers:
                    # Resolve the redirect target and loop to re-check it.
                    current = canonicalize(resp.headers["Location"], base=current)
                    continue

                body = await _read_capped(resp, config.max_page_bytes)
                content_type = resp.headers.get("Content-Type", "").split(";")[0].strip()
                return FetchResult(
                    url=current,
                    status=resp.status,
                    content_type=content_type,
                    body=body,
                )
        except (aiohttp.ClientError, TimeoutError) as exc:
            # TimeoutError: aiohttp raises asyncio timeouts directly, not as a
            # ClientError subclass — without this, a slow host would crash a
            # worker instead of counting as a retryable fetch failure.
            raise FetchError(f"fetch failed for {current}: {exc}") from exc

    raise FetchError(f"too many redirects starting from {url}")


async def _read_capped(resp: aiohttp.ClientResponse, cap: int) -> str:
    """Stream the body, aborting if it exceeds ``cap`` bytes.

    We cap while streaming rather than reading everything then checking length,
    so a hostile or accidental multi-gigabyte response cannot exhaust memory.
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in resp.content.iter_chunked(_READ_CHUNK):
        total += len(chunk)
        if total > cap:
            raise FetchError(f"response exceeded {cap} bytes")
        chunks.append(chunk)
    return b"".join(chunks).decode(resp.charset or "utf-8", errors="replace")
