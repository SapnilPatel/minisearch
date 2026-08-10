"""The fetcher pool — bounded concurrency (Milestone 3).

N async workers pull from the frontier and issue HTTP GETs over bounded channels,
giving natural backpressure: if the indexer falls behind, the channel fills and
fetchers block instead of accumulating an unbounded backlog. Handles timeouts,
retry with exponential backoff, robots.txt, max page size, and graceful shutdown.

Milestone 1 shipped the single-page fetch; Milestone 3 added the pool.
"""

from minisearch.fetcher.pool import Crawler, CrawlResult, CrawlStats
from minisearch.fetcher.single import (
    DisallowedError,
    FetchError,
    FetchResult,
    fetch_page,
)

__all__ = [
    "Crawler",
    "CrawlResult",
    "CrawlStats",
    "DisallowedError",
    "FetchError",
    "FetchResult",
    "fetch_page",
]
