"""The crawler worker pool.

N async workers pull URLs from the frontier, fetch them (with retry/backoff),
and hand results downstream over a **bounded** results queue. The bound is the
backpressure mechanism: if the consumer (the indexer, in later milestones) falls
behind, ``results.put`` blocks, the workers stall, and the crawl self-throttles
instead of accumulating an unbounded backlog in memory. This is the asyncio
equivalent of Go's bounded channels.

Politeness is enforced by the frontier's pop/host_done protocol: a worker locks
a host when it pops one of its URLs and releases it (starting the politeness
delay) only when the fetch — including the result hand-off — completes. Note
that ``host_done`` is called *after* ``results.put``, so backpressure also slows
the politeness clock rather than letting locked hosts pile up work.

Graceful shutdown: ``stop()`` flips an event; workers finish their in-flight
request (delivering its result) and exit before starting another. Nothing is
lost, nothing is duplicated, and ``crawl()`` returns normally with honest stats.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field

import aiohttp

from minisearch.config import Config
from minisearch.extract import Page, extract
from minisearch.fetcher.single import (
    DisallowedError,
    FetchError,
    FetchResult,
    fetch_page,
)
from minisearch.frontier import Frontier
from minisearch.robots.cache import RobotsCache

# How long an idle worker naps before re-checking the frontier / stop flag.
# Polling is a deliberate simplicity trade-off: at <=16 workers a 10ms nap costs
# ~nothing, and it avoids the condition-variable choreography a wake-on-add
# design needs. Revisit if worker counts grow by orders of magnitude.
_IDLE_NAP_S = 0.01

# Retryable HTTP statuses: server errors and 429 Too Many Requests.
_RETRYABLE = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class CrawlResult:
    """One crawled page: the raw fetch plus, for HTML, the extracted content.

    Extraction happens in the worker (not downstream) because the worker needs
    the outlinks anyway to feed the frontier — parsing once and shipping the
    result beats parsing twice. ``page`` is None for non-HTML responses.
    """

    fetch: FetchResult
    page: Page | None
    depth: int


@dataclass
class CrawlStats:
    fetched: int = 0        # pages fetched successfully (2xx) and delivered
    errors: int = 0         # pages given up on (exhausted retries or hard 4xx)
    disallowed: int = 0     # blocked by allowlist or robots.txt
    retries: int = 0        # individual retry attempts made
    elapsed_s: float = 0.0
    _started: float = field(default=0.0, repr=False)

    @property
    def pages_per_sec(self) -> float:
        return self.fetched / self.elapsed_s if self.elapsed_s > 0 else 0.0


class Crawler:
    """A bounded pool of fetch workers over a shared frontier.

    Usage: construct, then ``await crawl(seeds)`` while a consumer drains
    ``self.results``. The queue yields ``FetchResult`` items and a final ``None``
    sentinel when the crawl is over. Someone MUST consume the queue — it is
    bounded on purpose, and an unconsumed queue eventually blocks every worker
    (that is backpressure working as designed, not a bug).
    """

    def __init__(
        self,
        config: Config,
        *,
        max_pages: int | None = None,
        max_depth: int = 0,
        results_maxsize: int | None = None,
    ) -> None:
        self._config = config
        self._max_pages = max_pages
        # max_depth=0: fetch only the seeds. Depth d pages may enqueue links at
        # d+1 as long as d+1 <= max_depth — this is what closes the crawl loop.
        self._max_depth = max_depth
        self.frontier = Frontier(config)
        self.results: asyncio.Queue[CrawlResult | None] = asyncio.Queue(
            maxsize=results_maxsize or config.fetcher_workers * 2
        )
        self.stats = CrawlStats()
        self._stopping = asyncio.Event()
        self._in_flight = 0
        self._claimed = 0  # pages claimed against max_pages (claim-then-fetch)

    def stop(self) -> None:
        """Request a graceful shutdown: finish in-flight fetches, start no more."""
        self._stopping.set()

    async def crawl(self, seeds: list[str]) -> CrawlStats:
        """Crawl until the frontier drains, max_pages is reached, or stop()."""
        for url in seeds:
            self.frontier.add(url, depth=0)

        self.stats._started = time.monotonic()
        async with aiohttp.ClientSession() as session:
            robots = RobotsCache(self._config, session)
            workers = [
                asyncio.create_task(self._worker(session, robots))
                for _ in range(self._config.fetcher_workers)
            ]
            await asyncio.gather(*workers)

        self.stats.elapsed_s = time.monotonic() - self.stats._started
        await self.results.put(None)  # end-of-crawl sentinel for the consumer
        return self.stats

    # -- worker --------------------------------------------------------------

    async def _worker(self, session: aiohttp.ClientSession, robots: RobotsCache) -> None:
        while not self._stopping.is_set():
            # Budget check happens BEFORE popping, so an over-budget worker
            # never claims (and then would have to abandon) a URL.
            if self._max_pages is not None and self._claimed >= self._max_pages:
                break

            now = time.monotonic()
            item = self.frontier.pop_ready(now)
            if item is None:
                if len(self.frontier) == 0 and self._in_flight == 0:
                    break  # truly done: nothing queued, nothing being fetched
                # Either a politeness window or a busy host: nap and re-check.
                wait = self.frontier.time_until_ready(now)
                await asyncio.sleep(min(wait, _IDLE_NAP_S) if wait else _IDLE_NAP_S)
                continue

            self._claimed += 1
            self._in_flight += 1
            try:
                result = await self._fetch_with_retry(item.url, session, robots)
                if result is not None:
                    page: Page | None = None
                    if result.content_type == "text/html":
                        page = extract(result.url, result.body)
                        # Feed outlinks back to the frontier (the crawl loop).
                        # frontier.add dedups via the bloom filter, so a link
                        # every page carries (nav, footer) costs one entry.
                        if item.depth < self._max_depth:
                            for link in page.links:
                                self.frontier.add(link, depth=item.depth + 1)
                    self.stats.fetched += 1
                    # May block under backpressure — deliberately inside the
                    # host lock, so a slow consumer also slows the crawl.
                    await self.results.put(
                        CrawlResult(fetch=result, page=page, depth=item.depth)
                    )
            finally:
                self._in_flight -= 1
                self.frontier.host_done(item.host, time.monotonic())

    async def _fetch_with_retry(
        self,
        url: str,
        session: aiohttp.ClientSession,
        robots: RobotsCache,
    ) -> FetchResult | None:
        """Fetch with exponential backoff + jitter. None means no page to index."""
        base = self._config.retry_base_delay_s
        for attempt in range(self._config.max_retries + 1):
            try:
                result = await fetch_page(url, self._config, session, robots=robots)
            except DisallowedError:
                self.stats.disallowed += 1
                return None
            except FetchError:
                pass  # network-level failure: retryable
            else:
                if 200 <= result.status < 300:
                    return result
                if result.status not in _RETRYABLE:
                    # Hard 4xx: retrying cannot help, give up immediately.
                    self.stats.errors += 1
                    return None

            if attempt < self._config.max_retries:
                self.stats.retries += 1
                # Full jitter avoids retry stampedes when many URLs of one
                # slow host fail together.
                await asyncio.sleep(base * (2**attempt) + random.uniform(0, base))

        self.stats.errors += 1
        return None
