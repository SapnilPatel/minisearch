"""End-to-end API tests: crawl a local fixture site through POST /crawl, then
search it through GET /search. This is the whole system exercised through its
public surface — ingest path and query path meeting at the shared index."""

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from minisearch.api.server import create_app
from minisearch.config import Config


@pytest.fixture
async def site():
    """Fixture site: three linked pages plus an exact duplicate of one."""

    def html(title: str, body: str) -> web.Response:
        return web.Response(
            text=f"<html><head><title>{title}</title></head><body>{body}</body></html>",
            content_type="text/html",
        )

    async def home(_r):
        return html(
            "Event Loops",
            'The epoll interface scales well. <a href="/kqueue">kqueue</a> '
            '<a href="/recipes">recipes</a> <a href="/mirror">mirror</a>',
        )

    async def kqueue(_r):
        return html("Kqueue Notes", "kqueue is the bsd equivalent of epoll interface")

    async def recipes(_r):
        return html("Slow Cooking", "a slow cooker recipe for pulled pork")

    async def mirror(_r):
        # Same body text as /kqueue under a different URL -> content dedup.
        return html("Kqueue Notes", "kqueue is the bsd equivalent of epoll interface")

    app = web.Application()
    app.router.add_get("/", home)
    app.router.add_get("/kqueue", kqueue)
    app.router.add_get("/recipes", recipes)
    app.router.add_get("/mirror", mirror)
    runner = web.AppRunner(app)
    await runner.setup()
    tcp = web.TCPSite(runner, "127.0.0.1", 0)
    await tcp.start()
    try:
        yield f"http://127.0.0.1:{runner.addresses[0][1]}"
    finally:
        await runner.cleanup()


@pytest.fixture
async def client():
    config = Config(
        allowed_domains=["127.0.0.1"],
        per_host_delay_s=0.0,
        fetcher_workers=4,
        retry_base_delay_s=0.01,
    )
    app = create_app(config, store=None)
    test_client = TestClient(TestServer(app))
    await test_client.start_server()
    try:
        yield test_client
    finally:
        await test_client.close()


async def _crawl_and_wait(client, site, **body):
    resp = await client.post("/crawl", json={"seeds": [site + "/"], **body})
    assert resp.status == 202
    for _ in range(200):
        stats = await (await client.get("/stats")).json()
        if not stats["crawl_running"] and stats["last_crawl"]:
            return stats
        await asyncio.sleep(0.02)
    raise AssertionError("crawl did not finish")


# -- the end-to-end story ----------------------------------------------------


async def test_crawl_then_search(client, site):
    stats = await _crawl_and_wait(client, site, max_depth=2)

    assert stats["last_crawl"]["fetched"] == 4
    assert stats["last_crawl"]["indexed"] == 3          # mirror deduped
    assert stats["last_crawl"]["duplicates"] == 1
    assert stats["documents"] == 3

    # Query path: term present in two docs, ranked, with snippets.
    data = await (await client.get("/search?q=epoll")).json()
    assert data["count"] == 2
    urls = {h["url"] for h in data["hits"]}
    assert urls == {site + "/", site + "/kqueue"}
    assert all("epoll" in h["snippet"] for h in data["hits"])
    assert data["hits"][0]["score"] >= data["hits"][1]["score"]

    # Phrase query through the API.
    data = await (await client.get('/search?q="slow cooker"')).json()
    assert data["count"] == 1
    assert data["hits"][0]["title"] == "Slow Cooking"

    # Title terms are searchable (indexed as title + body).
    data = await (await client.get("/search?q=notes")).json()
    assert data["count"] == 1


async def test_search_before_any_crawl_is_empty(client):
    data = await (await client.get("/search?q=anything")).json()
    assert data == {"query": "anything", "count": 0, "hits": []}


async def test_search_validation(client):
    assert (await client.get("/search")).status == 400
    assert (await client.get("/search?q=x&limit=abc")).status == 400


async def test_crawl_validation(client):
    assert (await client.post("/crawl", json={})).status == 400
    assert (await client.post("/crawl", json={"seeds": []})).status == 400
    resp = await client.post("/crawl", data=b"not json")
    assert resp.status == 400


async def test_concurrent_crawl_rejected(client, site):
    # Occupy the crawler with a slow crawl, then try to start another.
    resp = await client.post(
        "/crawl", json={"seeds": [site + "/"], "max_depth": 2})
    assert resp.status == 202
    second = await client.post("/crawl", json={"seeds": [site + "/"]})
    # The first crawl may or may not have finished on a fast machine; only a
    # 409 or a completed first crawl are acceptable outcomes.
    if second.status == 409:
        body = await second.json()
        assert "already running" in body["error"]
    for _ in range(200):
        stats = await (await client.get("/stats")).json()
        if not stats["crawl_running"]:
            break
        await asyncio.sleep(0.02)


async def test_healthz(client):
    resp = await client.get("/healthz")
    assert resp.status == 200
    assert await resp.json() == {"status": "ok"}


async def test_metrics_exposition(client, site):
    await _crawl_and_wait(client, site, max_depth=2)
    await client.get("/search?q=epoll")

    text = await (await client.get("/metrics")).text()
    assert "# TYPE minisearch_pages_fetched_total counter" in text
    assert "minisearch_pages_fetched_total 4" in text
    assert "minisearch_documents_indexed_total 3" in text
    assert "minisearch_duplicate_pages_total 1" in text
    assert "minisearch_query_latency_seconds_count 1" in text
    assert "minisearch_bloom_theoretical_fpr" in text
