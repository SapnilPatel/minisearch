"""Integration tests for the Postgres store.

These run against a real PostgreSQL (local Homebrew service, or the postgres
service container in CI) — mocking the database would test the mock. If no
server is reachable the module skips rather than fails, so the rest of the
suite stays runnable on a machine without Postgres.

Each test runs against truncated tables (see the fixture) for isolation.
"""

import os

import pytest

from minisearch.analyze import analyze
from minisearch.store import Store

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://localhost:5432/minisearch"
)


@pytest.fixture
async def store():
    try:
        s = await Store.connect(DATABASE_URL)
    except OSError:
        pytest.skip(f"PostgreSQL not reachable at {DATABASE_URL}")
    await s.clear()
    try:
        yield s
    finally:
        await s.close()


def _doc(text: str):
    terms = analyze(text)
    return terms, sum(occ.tf for occ in terms.values())


async def test_persist_and_counts(store):
    terms, length = _doc("concurrent web crawler crawling the web")
    await store.persist_document("http://a.com/1", "T", "body", terms, length)
    counts = await store.counts()
    assert counts["documents"] == 1
    assert counts["terms"] == len(terms)
    assert counts["postings"] == len(terms)


async def test_persist_is_idempotent_per_url(store):
    terms, length = _doc("hello world")
    id1 = await store.persist_document("http://a.com/1", "T", "b", terms, length)
    id2 = await store.persist_document("http://a.com/1", "T2", "b2", terms, length)
    assert id1 == id2                       # same URL -> same document row
    assert (await store.counts())["documents"] == 1


async def test_load_index_round_trip(store):
    t1, l1 = _doc("apple banana apple")
    t2, l2 = _doc("banana cherry")
    await store.persist_document("http://a.com/1", "One", "apple banana apple", t1, l1)
    await store.persist_document("http://a.com/2", "Two", "banana cherry", t2, l2)

    index = await store.load_index()

    assert index.doc_count == 2
    assert index.avg_doc_length == (l1 + l2) / 2
    banana = index.postings("banana")
    assert [p.doc_id for p in banana] == sorted(p.doc_id for p in banana)
    assert index.doc_frequency("banana") == 2
    apple = index.postings("appl")
    assert apple[0].tf == 2 and apple[0].positions == (0, 2)
    # DocInfo survives: url, title, text (needed for snippets), length.
    info = index.doc(apple[0].doc_id)
    assert info.url == "http://a.com/1" and info.title == "One"
    assert info.text == "apple banana apple"


async def test_interrupted_crawl_resumes_where_it_left_off(store):
    # Persist two docs, "restart" (fresh load), index a third: ids continue,
    # postings stay sorted — the durable-crawl story end to end.
    t1, l1 = _doc("first document")
    t2, l2 = _doc("second document")
    await store.persist_document("http://a.com/1", "1", "x", t1, l1)
    await store.persist_document("http://a.com/2", "2", "y", t2, l2)

    index = await store.load_index()          # the "restart"
    t3, l3 = _doc("third document")
    new_id = index.add_document("http://a.com/3", "3", "z", t3, l3)

    assert new_id == 3
    doc_ids = [p.doc_id for p in index.postings("document")]
    assert doc_ids == sorted(doc_ids) == [1, 2, 3]
