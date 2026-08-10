"""The ingest pipeline's consumer half.

The Crawler produces CrawlResults into its bounded queue; the Indexer consumes
them: content-dedup -> analyze -> in-memory index -> (optionally) Postgres.
Producer and consumer are connected ONLY by that bounded queue — if indexing
(especially DB writes) falls behind, the queue fills and the fetchers throttle.
This file is where the backpressure story pays off.

Indexed text is ``title + body``: title words are strong relevance signals and
this makes them searchable. Positions refer to that combined token stream;
phrase adjacency within the body is unaffected (a title only shifts all body
positions by a constant).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from minisearch.analyze import analyze
from minisearch.dedup import ContentDeduper
from minisearch.fetcher.pool import CrawlResult
from minisearch.index import InvertedIndex
from minisearch.store import Store


@dataclass
class IndexStats:
    indexed: int = 0
    duplicates: int = 0
    skipped: int = 0     # non-HTML or non-200 results


class Indexer:
    def __init__(
        self,
        index: InvertedIndex,
        deduper: ContentDeduper | None = None,
        store: Store | None = None,
        on_indexed=None,
        on_duplicate=None,
    ) -> None:
        self._index = index
        self._deduper = deduper or ContentDeduper()
        self._store = store
        self._on_indexed = on_indexed        # metrics hooks (optional)
        self._on_duplicate = on_duplicate

    async def consume(self, queue: asyncio.Queue[CrawlResult | None]) -> IndexStats:
        """Drain the crawler's queue until the end-of-crawl sentinel."""
        stats = IndexStats()
        while (result := await queue.get()) is not None:
            if result.page is None or result.fetch.status != 200:
                stats.skipped += 1
                continue
            page = result.page

            # Content dedup runs on extracted text, not raw HTML, so markup
            # noise (ads, per-request tokens) can't defeat it.
            if self._deduper.seen_before(page.url, page.text):
                stats.duplicates += 1
                if self._on_duplicate:
                    self._on_duplicate()
                continue

            combined = f"{page.title} {page.text}" if page.title else page.text
            terms = analyze(combined)
            length = sum(occ.tf for occ in terms.values())
            self._index.add_document(
                url=page.url, title=page.title, text=page.text,
                terms=terms, length=length,
            )
            if self._store is not None:
                # Awaited inline — deliberately. A slow database keeps us
                # inside consume(), the queue fills, and the crawl slows: the
                # backpressure chain reaches all the way to the fetchers.
                await self._store.persist_document(
                    url=page.url, title=page.title, text=page.text,
                    terms=terms, length=length,
                )
            stats.indexed += 1
            if self._on_indexed:
                self._on_indexed()
        return stats
