"""Tests for the Indexer (the pipeline's consumer half) in isolation."""

import asyncio

from minisearch.extract import Page
from minisearch.fetcher.pool import CrawlResult
from minisearch.fetcher.single import FetchResult
from minisearch.index import InvertedIndex
from minisearch.pipeline import Indexer


def _result(url: str, title: str, text: str, status: int = 200) -> CrawlResult:
    return CrawlResult(
        fetch=FetchResult(url=url, status=status, content_type="text/html",
                          body=f"<html>{text}</html>"),
        page=Page(url=url, title=title, text=text, links=()),
        depth=0,
    )


async def _run(indexer: Indexer, *results: CrawlResult):
    queue: asyncio.Queue = asyncio.Queue()
    for r in results:
        await queue.put(r)
    await queue.put(None)
    return await indexer.consume(queue)


async def test_indexes_pages_and_dedups_content():
    index = InvertedIndex()
    stats = await _run(
        Indexer(index),
        _result("http://a/1", "One", "unique first page"),
        _result("http://a/2", "Two", "another distinct page"),
        _result("http://a/3", "Mirror", "unique first page"),   # dup text
    )
    assert stats.indexed == 2
    assert stats.duplicates == 1
    assert index.doc_count == 2


async def test_skips_non_html_and_errors():
    index = InvertedIndex()
    no_page = CrawlResult(
        fetch=FetchResult(url="http://a/f.pdf", status=200,
                          content_type="application/pdf", body=""),
        page=None, depth=0,
    )
    stats = await _run(Indexer(index), no_page,
                       _result("http://a/1", "T", "real page"))
    assert stats.skipped == 1
    assert stats.indexed == 1


async def test_title_terms_are_indexed():
    index = InvertedIndex()
    await _run(Indexer(index), _result("http://a/1", "Zebra Facts", "body words"))
    assert index.doc_frequency("zebra") == 1        # from the title
    assert index.doc_frequency("bodi") == 1         # from the body
