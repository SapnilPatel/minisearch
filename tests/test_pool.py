"""Integration tests for the crawler worker pool.

Same approach as test_fetch.py: a real aiohttp server on 127.0.0.1, so the pool
is exercised end to end — concurrency, per-host politeness, retry/backoff,
backpressure, max-pages budget, and graceful shutdown — without the internet.
Politeness tests use small real delays (tens of ms); everything else runs flat out.
"""

import asyncio
import time

import pytest
from aiohttp import web

from minisearch.config import Config
from minisearch.fetcher.pool import Crawler

PAGES = 12


@pytest.fixture
async def server():
    flaky_state = {"failures_left": 2}
    hits: list[str] = []

    async def page(request):
        hits.append(request.path)
        return web.Response(
            text=f"<html><body>page {request.match_info['n']}</body></html>",
            content_type="text/html",
        )

    async def flaky(_request):
        if flaky_state["failures_left"] > 0:
            flaky_state["failures_left"] -= 1
            raise web.HTTPInternalServerError()
        return web.Response(text="recovered", content_type="text/html")

    async def always_500(_request):
        raise web.HTTPInternalServerError()

    async def robots(_request):
        return web.Response(text="User-agent: *\nDisallow: /private\n")

    app = web.Application()
    app.router.add_get("/robots.txt", robots)
    app.router.add_get("/flaky", flaky)
    app.router.add_get("/always500", always_500)
    app.router.add_get(r"/p{n:\d+}", page)
    app.router.add_get("/private/x", page)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    try:
        yield {"base": f"http://127.0.0.1:{port}", "hits": hits}
    finally:
        await runner.cleanup()


def _config(**overrides) -> Config:
    defaults = dict(
        allowed_domains=["127.0.0.1"],
        per_host_delay_s=0.0,
        fetcher_workers=4,
        retry_base_delay_s=0.01,
        request_timeout_s=5.0,
    )
    defaults.update(overrides)
    return Config(**defaults)


async def _drain(crawler: Crawler) -> list:
    """Consume the results queue until the end-of-crawl sentinel."""
    out = []
    while (item := await crawler.results.get()) is not None:
        out.append(item)
    return out


async def test_crawls_all_seeds(server):
    crawler = Crawler(_config())
    seeds = [f"{server['base']}/p{i}" for i in range(PAGES)]
    crawl = asyncio.create_task(crawler.crawl(seeds))
    results = await _drain(crawler)
    stats = await crawl
    assert stats.fetched == PAGES
    assert len(results) == PAGES
    assert {r.status for r in results} == {200}


async def test_per_host_delay_is_enforced_under_concurrency(server):
    # 4 workers, one host, 4 pages, 50ms delay: despite idle workers, fetches
    # must be serialized with >= 3 gaps -> the crawl cannot finish in < 150ms.
    crawler = Crawler(_config(per_host_delay_s=0.05))
    seeds = [f"{server['base']}/p{i}" for i in range(4)]
    start = time.monotonic()
    crawl = asyncio.create_task(crawler.crawl(seeds))
    await _drain(crawler)
    stats = await crawl
    elapsed = time.monotonic() - start
    assert stats.fetched == 4
    assert elapsed >= 0.15


async def test_retry_recovers_from_transient_5xx(server):
    crawler = Crawler(_config())
    crawl = asyncio.create_task(crawler.crawl([f"{server['base']}/flaky"]))
    results = await _drain(crawler)
    stats = await crawl
    assert stats.fetched == 1
    assert stats.retries == 2          # failed twice, then succeeded
    assert results[0].body == "recovered"


async def test_retry_gives_up_after_max_retries(server):
    crawler = Crawler(_config(max_retries=2))
    crawl = asyncio.create_task(crawler.crawl([f"{server['base']}/always500"]))
    results = await _drain(crawler)
    stats = await crawl
    assert results == []
    assert stats.fetched == 0
    assert stats.errors == 1
    assert stats.retries == 2


async def test_4xx_is_not_retried(server):
    crawler = Crawler(_config())
    crawl = asyncio.create_task(crawler.crawl([f"{server['base']}/nosuchpage"]))
    results = await _drain(crawler)
    stats = await crawl
    assert results == []
    assert stats.errors == 1
    assert stats.retries == 0


async def test_robots_disallowed_is_skipped_not_errored(server):
    crawler = Crawler(_config())
    crawl = asyncio.create_task(
        crawler.crawl([f"{server['base']}/private/x", f"{server['base']}/p0"])
    )
    results = await _drain(crawler)
    stats = await crawl
    assert stats.fetched == 1
    assert stats.disallowed == 1
    assert len(results) == 1


async def test_max_pages_budget(server):
    crawler = Crawler(_config(), max_pages=5)
    seeds = [f"{server['base']}/p{i}" for i in range(PAGES)]
    crawl = asyncio.create_task(crawler.crawl(seeds))
    results = await _drain(crawler)
    stats = await crawl
    assert stats.fetched == 5
    assert len(results) == 5


async def test_backpressure_with_tiny_results_queue(server):
    # results queue of 1 and a deliberately slow consumer: the pool must block
    # (not drop, not crash) and still deliver every page.
    crawler = Crawler(_config(), results_maxsize=1)
    seeds = [f"{server['base']}/p{i}" for i in range(PAGES)]
    crawl = asyncio.create_task(crawler.crawl(seeds))
    results = []
    while (item := await crawler.results.get()) is not None:
        results.append(item)
        await asyncio.sleep(0.01)      # slow consumer
    stats = await crawl
    assert stats.fetched == PAGES
    assert len(results) == PAGES


async def test_graceful_shutdown_mid_crawl(server):
    # Stop after 3 results: in-flight work completes and is delivered, no new
    # fetches start, the sentinel arrives, and crawl() returns cleanly.
    crawler = Crawler(_config(per_host_delay_s=0.02))
    seeds = [f"{server['base']}/p{i}" for i in range(50)]
    crawl = asyncio.create_task(crawler.crawl(seeds))

    results = []
    while (item := await crawler.results.get()) is not None:
        results.append(item)
        if len(results) == 3:
            crawler.stop()
    stats = await asyncio.wait_for(crawl, timeout=5.0)   # must not hang

    assert 3 <= stats.fetched < 50
    assert stats.fetched == len(results)                  # nothing lost or dropped
