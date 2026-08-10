"""Per-host robots.txt fetching and caching.

Fetches ``scheme://host/robots.txt`` once per host, parses it for our user-agent,
and caches the result so a crawl consults each host's rules exactly once.
"""

from __future__ import annotations

import aiohttp

from minisearch.config import Config
from minisearch.robots.parser import RobotsRules, parse_robots


class RobotsCache:
    """Async cache of parsed robots rules, keyed by (scheme, host[:port])."""

    def __init__(self, config: Config, session: aiohttp.ClientSession) -> None:
        self._config = config
        self._session = session
        self._cache: dict[tuple[str, str], RobotsRules] = {}

    async def get(self, scheme: str, host: str) -> RobotsRules:
        key = (scheme, host)
        cached = self._cache.get(key)
        if cached is None:
            cached = await self._fetch(scheme, host)
            self._cache[key] = cached
        return cached

    async def _fetch(self, scheme: str, host: str) -> RobotsRules:
        url = f"{scheme}://{host}/robots.txt"
        timeout = aiohttp.ClientTimeout(total=self._config.request_timeout_s)
        headers = {"User-Agent": self._config.user_agent}
        try:
            async with self._session.get(
                url, timeout=timeout, headers=headers
            ) as resp:
                # 4xx (incl. 404 "no robots.txt") -> no restrictions.
                # 5xx / unreachable -> fail open (allow). Our hard safety rail is
                # the ALLOWED_DOMAINS allowlist, not robots; a flaky robots.txt
                # should not silently halt a crawl. (Google's crawler instead
                # treats 5xx as a temporary full disallow — a defensible
                # alternative; we favor the allowlist as the real guard.)
                if resp.status >= 400:
                    return RobotsRules()
                text = await resp.text()
        except (aiohttp.ClientError, TimeoutError):
            return RobotsRules()
        return parse_robots(text, self._config.user_agent)
