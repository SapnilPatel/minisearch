"""Benchmark: crawler throughput (pages/sec) against a local server.

Spins a local aiohttp server on 127.0.0.1 serving small HTML pages, seeds N
URLs, and measures wall-clock crawl throughput with the politeness delay set to
zero (we are benchmarking the pool, and 127.0.0.1 is one host — a nonzero delay
would measure the delay, not the crawler).

Numbers from localhost are an upper bound on the pool's overhead, not a claim
about internet crawling — real crawls are dominated by network latency and
politeness. Run at least 3 times and record the spread (see METRICS.md rules).

Usage:  python scripts/bench_crawl.py [pages] [workers]
"""

import asyncio
import resource
import sys
import time

from aiohttp import web

from minisearch.config import Config
from minisearch.fetcher.pool import Crawler

BODY = "<html><head><title>p</title></head><body>" + "word " * 200 + "</body></html>"


async def _page(_request):
    return web.Response(text=BODY, content_type="text/html")


async def _robots(_request):
    return web.Response(text="User-agent: *\nAllow: /\n")


async def main(pages: int, workers: int) -> None:
    app = web.Application()
    app.router.add_get("/robots.txt", _robots)
    app.router.add_get(r"/p{n:\d+}", _page)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]

    config = Config(
        allowed_domains=["127.0.0.1"],
        per_host_delay_s=0.0,
        fetcher_workers=workers,
    )
    crawler = Crawler(config)
    seeds = [f"http://127.0.0.1:{port}/p{i}" for i in range(pages)]

    async def consume() -> int:
        n = 0
        while await crawler.results.get() is not None:
            n += 1
        return n

    start = time.monotonic()
    consumer = asyncio.create_task(consume())
    stats = await crawler.crawl(seeds)
    consumed = await consumer
    wall = time.monotonic() - start

    await runner.cleanup()

    peak_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024)
    print(f"pages={stats.fetched} consumed={consumed} errors={stats.errors}")
    print(f"wall={wall:.3f}s  throughput={stats.fetched / wall:.0f} pages/sec")
    print(f"peak_rss={peak_rss_mb:.1f} MB")


if __name__ == "__main__":
    n_pages = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    n_workers = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    asyncio.run(main(n_pages, n_workers))
