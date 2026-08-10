"""PostgreSQL persistence for the index.

The in-memory index serves queries; Postgres makes crawls durable — a restart
reloads the index instead of throwing the crawl away. Writes happen per
document inside ONE transaction (document row + term upserts + postings), so an
interrupted crawl leaves no half-indexed documents: every document is either
fully persisted or absent.

Posting inserts are **batched** (one executemany per document, and COPY for
bulk loads) rather than issued row by row. The measured difference is large —
see METRICS.md and scripts/bench_inserts.py — because row-by-row pays a
round-trip and a fsync'd commit per posting, while a batch pays one of each per
document.
"""

from __future__ import annotations

from hashlib import blake2b

import asyncpg

from minisearch.analyze import TermOccurrences
from minisearch.index import DocInfo, InvertedIndex, Posting


class Store:
    """asyncpg-backed persistence. Create with :meth:`connect`."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, database_url: str) -> Store:
        pool = await asyncpg.create_pool(database_url, min_size=1, max_size=4)
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def apply_schema(self, schema_sql: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(schema_sql)

    async def clear(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE postings, terms, documents, crawl_queue RESTART IDENTITY"
            )

    # -- write path ----------------------------------------------------------

    async def persist_document(
        self,
        url: str,
        title: str,
        text: str,
        terms: dict[str, TermOccurrences],
        length: int,
    ) -> int:
        """Persist one document and its postings atomically; returns doc id.

        One transaction per document: the document row, any new terms, the
        doc_frequency bumps, and all postings commit together or not at all —
        that is the answer to "what happens if the crawl dies halfway".
        """
        content_hash = blake2b(text.encode("utf-8"), digest_size=16).digest()
        async with self._pool.acquire() as conn, conn.transaction():
            doc_id: int = await conn.fetchval(
                """
                INSERT INTO documents (url, title, text, content_hash, length)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (url) DO UPDATE
                    SET title = $2, text = $3, content_hash = $4, length = $5,
                        fetched_at = now()
                RETURNING id
                """,
                url, title, text, content_hash, length,
            )

            term_list = list(terms)
            # Upsert the dictionary entries and bump doc_frequency in one
            # statement; RETURNING gives us the term ids for the postings.
            rows = await conn.fetch(
                """
                INSERT INTO terms (term, doc_frequency)
                SELECT t, 1 FROM unnest($1::text[]) AS t
                ON CONFLICT (term) DO UPDATE
                    SET doc_frequency = terms.doc_frequency + 1
                RETURNING id, term
                """,
                term_list,
            )
            term_ids = {row["term"]: row["id"] for row in rows}

            # The batch insert: one executemany for all of this document's
            # postings, inside the already-open transaction.
            await conn.executemany(
                """
                INSERT INTO postings (term_id, doc_id, tf, positions)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (term_id, doc_id) DO UPDATE
                    SET tf = $3, positions = $4
                """,
                [
                    (term_ids[term], doc_id, occ.tf, list(occ.positions))
                    for term, occ in terms.items()
                ],
            )
        return doc_id

    # -- read path (restart recovery) ----------------------------------------

    async def load_index(self) -> InvertedIndex:
        """Rebuild an in-memory index from what the store holds.

        Documents stream in ascending id order, so restored posting lists come
        out sorted by construction — same invariant as live indexing.
        """
        index = InvertedIndex()
        async with self._pool.acquire() as conn:
            docs = await conn.fetch(
                "SELECT id, url, title, text, length FROM documents ORDER BY id"
            )
            postings = await conn.fetch(
                """
                SELECT p.doc_id, t.term, p.tf, p.positions
                FROM postings p JOIN terms t ON t.id = p.term_id
                ORDER BY p.doc_id
                """
            )

        by_doc: dict[int, dict[str, Posting]] = {}
        for row in postings:
            by_doc.setdefault(row["doc_id"], {})[row["term"]] = Posting(
                doc_id=row["doc_id"],
                tf=row["tf"],
                positions=tuple(row["positions"]),
            )
        for row in docs:
            index.restore_document(
                row["id"],
                DocInfo(
                    url=row["url"], title=row["title"] or "",
                    length=row["length"], text=row["text"],
                ),
                by_doc.get(row["id"], {}),
            )
        return index

    # -- stats ----------------------------------------------------------------

    async def counts(self) -> dict[str, int]:
        async with self._pool.acquire() as conn:
            return {
                "documents": await conn.fetchval("SELECT count(*) FROM documents"),
                "terms": await conn.fetchval("SELECT count(*) FROM terms"),
                "postings": await conn.fetchval("SELECT count(*) FROM postings"),
            }
