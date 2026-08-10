"""Benchmark: posting-insert strategies in PostgreSQL.

The spec's Milestone 6 measurement: batch inserts inside a transaction vs
row-by-row, on identical data. Three strategies:

1. row-by-row, autocommit  — one INSERT + one committed transaction per posting.
   Pays a client round-trip AND a WAL fsync per row. The naive baseline.
2. executemany, one tx     — all rows in one transaction, statement prepared
   once, one fsync at commit.
3. COPY, one tx            — Postgres's bulk-load path (asyncpg
   copy_records_to_table), the fastest way in.

Usage:  python scripts/bench_inserts.py [rows]   (default 5000)
Run against the local minisearch db; uses a throwaway table, three runs each.
"""

import asyncio
import os
import statistics
import sys
import time

import asyncpg

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost:5432/minisearch")
RUNS = 3


def make_rows(n: int) -> list[tuple[int, int, int, list[int]]]:
    return [(i, i * 7 % 1000, 1 + i % 5, [i, i + 2, i + 9]) for i in range(n)]


async def setup(conn: asyncpg.Connection) -> None:
    await conn.execute(
        """
        DROP TABLE IF EXISTS bench_postings;
        CREATE TABLE bench_postings (
            term_id BIGINT, doc_id BIGINT, tf INT, positions INT[],
            PRIMARY KEY (term_id, doc_id)
        )
        """
    )


async def bench(name: str, fn, conn, rows) -> float:
    times = []
    for _ in range(RUNS):
        await conn.execute("TRUNCATE bench_postings")
        start = time.monotonic()
        await fn(conn, rows)
        times.append(time.monotonic() - start)
    med = statistics.median(times)
    lo, hi = min(times), max(times)
    n = len(rows)
    print(
        f"{name:<28} median {med:7.3f}s  [{lo:.3f}–{hi:.3f}]  "
        f"{n / med:>10,.0f} rows/sec"
    )
    return med


async def row_by_row_autocommit(conn, rows):
    # No explicit transaction: every execute is its own committed transaction.
    for r in rows:
        await conn.execute(
            "INSERT INTO bench_postings VALUES ($1, $2, $3, $4)", *r
        )


async def executemany_one_tx(conn, rows):
    async with conn.transaction():
        await conn.executemany(
            "INSERT INTO bench_postings VALUES ($1, $2, $3, $4)", rows
        )


async def copy_one_tx(conn, rows):
    async with conn.transaction():
        await conn.copy_records_to_table("bench_postings", records=rows)


async def main(n: int) -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    await setup(conn)
    rows = make_rows(n)
    print(f"{n:,} posting rows, median of {RUNS} runs each\n")

    slow = await bench("row-by-row (autocommit)", row_by_row_autocommit, conn, rows)
    batch = await bench("executemany (one tx)", executemany_one_tx, conn, rows)
    copy = await bench("COPY (one tx)", copy_one_tx, conn, rows)

    print(
        f"\nspeedup vs row-by-row:  executemany {slow / batch:.0f}x   "
        f"COPY {slow / copy:.0f}x"
    )
    await conn.execute("DROP TABLE bench_postings")
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 5000))
