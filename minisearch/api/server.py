"""The REST API.

    POST /crawl    {"seeds": [...], "max_pages": N, "max_depth": D}  -> 202
    GET  /search   ?q=...&limit=10
    GET  /stats
    GET  /healthz
    GET  /metrics   (Prometheus text format)

One process serves both paths: the ingest path runs as a background task pair
(crawler producing, indexer consuming) while queries read the shared in-memory
index. asyncio's single-threaded model is what makes that safe without locks —
index mutations and reads interleave at await points, never mid-operation.

Only one crawl runs at a time (409 otherwise): the frontier, bloom filter, and
politeness state are per-crawl, and overlapping crawls would fight over them.
"""

from __future__ import annotations

import asyncio
import time

from aiohttp import web

from minisearch.config import Config
from minisearch.dedup import ContentDeduper
from minisearch.fetcher.pool import Crawler
from minisearch.index import InvertedIndex
from minisearch.metrics import Registry
from minisearch.pipeline import Indexer, IndexStats
from minisearch.query import QueryEngine
from minisearch.store import Store

_STATE = web.AppKey("minisearch_state", object)


class AppState:
    def __init__(self, config: Config, store: Store | None = None) -> None:
        self.config = config
        self.store = store
        self.index = InvertedIndex()
        self.engine = QueryEngine(self.index, k1=config.bm25_k1, b=config.bm25_b)
        self.deduper = ContentDeduper()
        self.crawler: Crawler | None = None
        self.crawl_task: asyncio.Task | None = None
        self.last_crawl: dict | None = None

        self.registry = Registry()
        self.m_pages = self.registry.counter(
            "minisearch_pages_fetched_total", "Pages fetched successfully")
        self.m_fetch_errors = self.registry.counter(
            "minisearch_fetch_errors_total", "Fetches given up on after retries")
        self.m_disallowed = self.registry.counter(
            "minisearch_fetches_disallowed_total", "Fetches blocked by allowlist/robots")
        self.m_indexed = self.registry.counter(
            "minisearch_documents_indexed_total", "Documents added to the index")
        self.m_duplicates = self.registry.counter(
            "minisearch_duplicate_pages_total", "Pages skipped by content dedup")
        self.m_frontier = self.registry.gauge(
            "minisearch_frontier_depth", "URLs currently queued in the frontier")
        self.m_bloom_fpr = self.registry.gauge(
            "minisearch_bloom_theoretical_fpr",
            "Bloom filter theoretical FPR at current load")
        self.m_query_latency = self.registry.histogram(
            "minisearch_query_latency_seconds", "Search request latency")

    @property
    def crawl_running(self) -> bool:
        return self.crawl_task is not None and not self.crawl_task.done()


def create_app(config: Config, store: Store | None = None) -> web.Application:
    app = web.Application()
    app[_STATE] = AppState(config, store=store)
    app.router.add_post("/crawl", handle_crawl)
    app.router.add_get("/search", handle_search)
    app.router.add_get("/stats", handle_stats)
    app.router.add_get("/healthz", handle_healthz)
    app.router.add_get("/metrics", handle_metrics)
    return app


def _state(request: web.Request) -> AppState:
    return request.app[_STATE]


async def handle_crawl(request: web.Request) -> web.Response:
    state = _state(request)
    if state.crawl_running:
        return web.json_response(
            {"error": "a crawl is already running"}, status=409)

    try:
        body = await request.json()
        seeds = body["seeds"]
        if not isinstance(seeds, list) or not seeds:
            raise ValueError("seeds must be a non-empty list")
        max_pages = body.get("max_pages")
        max_depth = int(body.get("max_depth", 2))
    except (ValueError, KeyError, TypeError) as exc:
        return web.json_response({"error": f"bad request: {exc}"}, status=400)

    state.crawl_task = asyncio.create_task(
        _run_crawl(state, seeds, max_pages, max_depth))
    return web.json_response({"status": "started", "seeds": len(seeds)}, status=202)


async def _run_crawl(
    state: AppState, seeds: list[str], max_pages: int | None, max_depth: int
) -> None:
    crawler = Crawler(state.config, max_pages=max_pages, max_depth=max_depth)
    state.crawler = crawler
    indexer = Indexer(
        state.index,
        deduper=state.deduper,
        store=state.store,
        on_indexed=state.m_indexed.inc,
        on_duplicate=state.m_duplicates.inc,
    )
    consume = asyncio.create_task(indexer.consume(crawler.results))
    crawl_stats = await crawler.crawl(seeds)
    index_stats: IndexStats = await consume

    state.m_pages.inc(crawl_stats.fetched)
    state.m_fetch_errors.inc(crawl_stats.errors)
    state.m_disallowed.inc(crawl_stats.disallowed)
    state.last_crawl = {
        "fetched": crawl_stats.fetched,
        "errors": crawl_stats.errors,
        "disallowed": crawl_stats.disallowed,
        "retries": crawl_stats.retries,
        "indexed": index_stats.indexed,
        "duplicates": index_stats.duplicates,
        "elapsed_s": round(crawl_stats.elapsed_s, 3),
        "pages_per_sec": round(crawl_stats.pages_per_sec, 1),
    }


async def handle_search(request: web.Request) -> web.Response:
    state = _state(request)
    q = request.query.get("q", "").strip()
    if not q:
        return web.json_response({"error": "missing query parameter q"}, status=400)
    try:
        limit = min(int(request.query.get("limit", 10)), 100)
    except ValueError:
        return web.json_response({"error": "limit must be an integer"}, status=400)

    start = time.monotonic()
    hits = state.engine.search(q, limit=limit)
    state.m_query_latency.observe(time.monotonic() - start)

    return web.json_response({
        "query": q,
        "count": len(hits),
        "hits": [
            {"url": h.url, "title": h.title,
             "score": round(h.score, 4), "snippet": h.snippet}
            for h in hits
        ],
    })


async def handle_stats(request: web.Request) -> web.Response:
    state = _state(request)
    if state.crawler is not None:
        state.m_frontier.set(len(state.crawler.frontier))
        state.m_bloom_fpr.set(
            state.crawler.frontier._seen.theoretical_fpr())  # noqa: SLF001
    return web.json_response({
        "documents": state.index.doc_count,
        "unique_terms": state.index.term_count,
        "avg_doc_length": round(state.index.avg_doc_length, 1),
        "dedup": state.deduper.stats,
        "crawl_running": state.crawl_running,
        "last_crawl": state.last_crawl,
    })


async def handle_healthz(_request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def handle_metrics(request: web.Request) -> web.Response:
    state = _state(request)
    if state.crawler is not None:
        state.m_frontier.set(len(state.crawler.frontier))
        state.m_bloom_fpr.set(
            state.crawler.frontier._seen.theoretical_fpr())  # noqa: SLF001
    return web.Response(
        text=state.registry.render(),
        content_type="text/plain",
        charset="utf-8",
    )


def main() -> None:
    """Entry point: load config, connect the store if reachable, serve."""
    config = Config.from_env()

    async def _serve() -> None:
        store: Store | None = None
        try:
            store = await Store.connect(config.database_url)
            print(f"store: connected to {config.database_url}")
        except OSError as exc:
            print(f"store: unavailable ({exc}); running in-memory only")

        app = create_app(config, store=store)
        if store is not None:
            # Restart durability: reload the index persisted by earlier crawls.
            state: AppState = app[_STATE]
            state.index = await store.load_index()
            state.engine = QueryEngine(
                state.index, k1=config.bm25_k1, b=config.bm25_b)
            print(f"store: restored {state.index.doc_count} documents")

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, config.api_host, config.api_port)
        await site.start()
        print(f"minisearch listening on http://{config.api_host}:{config.api_port}")
        await asyncio.Event().wait()   # serve forever

    asyncio.run(_serve())


if __name__ == "__main__":
    main()
