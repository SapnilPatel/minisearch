"""Integration tests for single-page fetch.

A tiny aiohttp server runs on 127.0.0.1 (ephemeral port) serving fixture routes,
so these tests exercise the real fetch path — allowlist gate, robots gate,
manual redirect handling with per-hop re-checks, and the streaming size cap —
without touching the internet.
"""

import aiohttp
import pytest
from aiohttp import web

from minisearch.config import Config
from minisearch.fetcher.single import DisallowedError, FetchError, fetch_page
from minisearch.robots.cache import RobotsCache

ROBOTS_TXT = "User-agent: *\nDisallow: /blocked\n"


async def _root(_request):
    return web.Response(text="<html><body>Hello</body></html>", content_type="text/html")


async def _robots(_request):
    return web.Response(text=ROBOTS_TXT, content_type="text/plain")


async def _big(_request):
    return web.Response(body=b"x" * 100_000)


async def _redirect(_request):
    raise web.HTTPFound(location="/target")


async def _target(_request):
    return web.Response(text="arrived", content_type="text/html")


async def _ext_redirect(_request):
    # Redirect to a host that is NOT on the allowlist.
    raise web.HTTPFound(location="http://example.com/evil")


async def _blocked(_request):
    return web.Response(text="should be blocked by robots", content_type="text/html")


@pytest.fixture
async def server():
    app = web.Application()
    app.router.add_get("/", _root)
    app.router.add_get("/robots.txt", _robots)
    app.router.add_get("/big", _big)
    app.router.add_get("/redirect", _redirect)
    app.router.add_get("/target", _target)
    app.router.add_get("/ext-redirect", _ext_redirect)
    app.router.add_get("/blocked", _blocked)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        await runner.cleanup()


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s


def _config(**overrides) -> Config:
    return Config(allowed_domains=["127.0.0.1"], **overrides)


async def test_fetch_ok(server, session):
    res = await fetch_page(server + "/", _config(), session)
    assert res.status == 200
    assert "Hello" in res.body
    assert res.content_type == "text/html"


async def test_host_not_on_allowlist_is_refused(server, session):
    cfg = Config(allowed_domains=["example.org"])  # 127.0.0.1 not allowed
    with pytest.raises(DisallowedError):
        await fetch_page(server + "/", cfg, session)


async def test_robots_blocks_disallowed_path(server, session):
    cfg = _config()
    robots = RobotsCache(cfg, session)
    with pytest.raises(DisallowedError):
        await fetch_page(server + "/blocked", cfg, session, robots=robots)
    # A path robots allows still succeeds (and reuses the cached robots.txt).
    res = await fetch_page(server + "/", cfg, session, robots=robots)
    assert res.status == 200


async def test_size_cap_aborts_large_body(server, session):
    with pytest.raises(FetchError):
        await fetch_page(server + "/big", _config(max_page_bytes=10), session)


async def test_redirect_is_followed(server, session):
    res = await fetch_page(server + "/redirect", _config(), session)
    assert res.status == 200
    assert res.url.endswith("/target")


async def test_redirect_to_disallowed_host_is_refused(server, session):
    # The entry URL is allowed, but the redirect target host is not — the
    # per-hop re-check must catch it.
    with pytest.raises(DisallowedError):
        await fetch_page(server + "/ext-redirect", _config(), session)
