"""Benchmark: index throughput, query latency (p50/p99), memory, and the
smallest-first intersection speedup.

Builds a synthetic corpus with a skewed (Zipf-like) term distribution — like
real text, a few terms appear in most documents and most terms appear in few —
then measures:

1. documents indexed/sec (full analyze + index cost)
2. corpus size vs in-memory index size (tracemalloc around the build)
3. query latency p50/p99 for single-term, 2-term AND, and phrase queries
4. 3-term AND folded smallest-list-first vs largest-first. (For two lists a
   two-pointer merge is O(|a|+|b|) either way; the fold ORDER only pays off
   from three lists up, when a small intermediate keeps later merges cheap.)

Deterministic corpus (seeded RNG). Timing rules per METRICS.md: report median
of 3 full runs for throughput; latency percentiles over 500 queries each.

Usage:  python scripts/bench_query.py [docs]     (default 20000)
"""

import random
import statistics
import sys
import time
import tracemalloc

from minisearch.analyze import analyze
from minisearch.index import InvertedIndex
from minisearch.query import QueryEngine, intersect

DOC_WORDS = 120
RUNS = 3
QUERY_REPS = 500


def make_corpus(n_docs: int) -> list[str]:
    rng = random.Random(42)
    # Vocabulary tiers approximating a Zipf distribution.
    common = [f"common{i}" for i in range(20)]          # in most docs
    medium = [f"medium{i}" for i in range(500)]
    rare = [f"rare{i}" for i in range(20_000)]
    docs = []
    for _ in range(n_docs):
        words = (
            rng.choices(common, k=DOC_WORDS // 2)
            + rng.choices(medium, k=DOC_WORDS // 3)
            + rng.choices(rare, k=DOC_WORDS - DOC_WORDS // 2 - DOC_WORDS // 3)
        )
        rng.shuffle(words)
        docs.append(" ".join(words))
    return docs


def build_index(docs: list[str]) -> InvertedIndex:
    idx = InvertedIndex()
    for i, text in enumerate(docs):
        terms = analyze(text)
        idx.add_document(
            url=f"http://corpus/{i}", title="", text=text, terms=terms,
            length=sum(o.tf for o in terms.values()),
        )
    return idx


def pctl(samples: list[float], p: float) -> float:
    return statistics.quantiles(samples, n=100)[int(p) - 1]


def time_queries(engine: QueryEngine, query: str, reps: int) -> list[float]:
    times = []
    for _ in range(reps):
        start = time.perf_counter()
        engine.search(query, limit=10)
        times.append(time.perf_counter() - start)
    return times


def main(n_docs: int) -> None:
    docs = make_corpus(n_docs)
    corpus_bytes = sum(len(d.encode()) for d in docs)
    print(f"corpus: {n_docs:,} docs, {DOC_WORDS} words each, "
          f"{corpus_bytes / 1e6:.1f} MB of text\n")

    # 1. index throughput (median of RUNS full builds)
    build_times = []
    for _ in range(RUNS):
        start = time.perf_counter()
        idx = build_index(docs)
        build_times.append(time.perf_counter() - start)
    med = statistics.median(build_times)
    print(f"index throughput: {n_docs / med:,.0f} docs/sec  "
          f"(median of {RUNS}: {med:.2f}s, spread "
          f"{min(build_times):.2f}–{max(build_times):.2f}s)")

    # 2. index memory (tracemalloc around one clean build)
    tracemalloc.start()
    before = tracemalloc.take_snapshot()
    idx = build_index(docs)
    after = tracemalloc.take_snapshot()
    tracemalloc.stop()
    index_bytes = sum(s.size_diff for s in after.compare_to(before, "filename"))
    print(f"index memory: {index_bytes / 1e6:.1f} MB for {corpus_bytes / 1e6:.1f} MB "
          f"of text ({index_bytes / corpus_bytes:.2f}x corpus size)\n")

    engine = QueryEngine(idx)

    # 3. query latency percentiles
    for label, q in [
        ("single common term", "common3"),
        ("single rare term", "rare42"),
        ("2-term AND (common+medium)", "common3 medium17"),
        ("phrase", '"common3 medium17"'),
    ]:
        times = time_queries(engine, q, QUERY_REPS)
        print(f"{label:<28} p50 {pctl(times, 50) * 1e3:7.2f} ms   "
              f"p99 {pctl(times, 99) * 1e3:7.2f} ms   "
              f"({len(engine.search(q))} hits)")

    # 4. fold-order experiment: 3-term AND, ascending vs descending df
    lists = sorted(
        (idx.postings("rare42"), idx.postings("medium17"), idx.postings("common3")),
        key=len,
    )
    print(f"\nfold-order (3-term AND, df sizes: {[len(x) for x in lists]}):")

    def fold(order):
        start = time.perf_counter()
        for _ in range(200):
            acc = order[0]
            for other in order[1:]:
                acc = intersect(acc, other)
        return (time.perf_counter() - start) / 200

    asc = statistics.median(fold(lists) for _ in range(RUNS))
    desc = statistics.median(fold(lists[::-1]) for _ in range(RUNS))
    print(f"  smallest-first {asc * 1e3:.3f} ms   "
          f"largest-first {desc * 1e3:.3f} ms   speedup {desc / asc:.1f}x")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 20_000)
