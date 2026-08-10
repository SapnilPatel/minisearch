# Measured performance

Real numbers, recorded as each milestone lands. These become resume bullets, so
they must be honest and reproducible.

**Rules (learned the hard way):**
1. Run every benchmark **at least three times**; report a representative run
   with the spread, not the best one.
2. Measure **memory, not just speed** — throughput benchmarks reward the eager
   allocation that wrecks memory behavior and will never warn you about it.
3. Record the machine and conditions so a number means something later.

## Environment

| Field | Value |
|---|---|
| Machine | Apple M4, 16 GB RAM, macOS (Darwin 25.5) |
| Python | 3.13.5 |

## Results

| Metric | Milestone | Value | Notes |
|---|---|---|---|
| Pages crawled/sec | 3 | **~7,400 pages/sec** (7375 / 7408 / 7419 over 3 runs; 1,000 pages, 8 workers, ~1 KB pages, localhost, politeness delay 0) | headline throughput. Localhost = upper bound on pool overhead; real crawls are network/politeness-bound. Peak RSS 40.4 MB. `scripts/bench_crawl.py` |
| Documents indexed/sec | 6 | **~3,440 docs/sec** full analyze+index cost (3,419 / 3,444 / 3,465 across three 3-run medians; 20k docs x 120 words, synthetic Zipf corpus). `scripts/bench_query.py` | ingest performance |
| Batch vs row-by-row insert speedup | 6 | **36x** executemany-in-one-tx (387,603 vs 10,766 rows/sec), **56x** COPY (602,488 rows/sec). 5,000 posting rows, median of 3 runs, spreads tight (row-by-row 0.449–0.477s). Row-by-row pays a round-trip + WAL fsync per row; a batch pays one each per transaction. `scripts/bench_inserts.py` | DB optimization |
| Query latency p50 / p99 | 7 | 20k-doc index, 500 reps each, stable across 3 runs: **rare term 1.03 / 1.2 ms** · **2-term AND 2.6 / ~3 ms** · **common term 13.5 / ~16 ms** (scores ~19k candidates — bounded top-K keeps memory flat but scoring is O(matches)) · **phrase 9.1 ms p50, ~182 ms p99** (p99 spikes on position-set building for high-df phrase terms — honest outlier, see DESIGN.md future work). `scripts/bench_query.py` | the SDE headline number |
| Corpus size vs index size | 6 | **186.7 MB index for 21.8 MB of text (8.6x)** — Python object overhead per posting dominates; delta-encoded packed postings are the known fix (documented, not built). tracemalloc, 20k docs | storage efficiency |
| Bloom filter FPR: measured vs theoretical | 4 | **1.020% measured vs 1.004% predicted** at design load (100k items, m=958,512 bits, k=7, 200k distinct probes). Ratio stays 1.00–1.02 from 75% load through 2x overload (5.786% vs 5.788% at 150%; 15.678% vs 15.745% at 200%). Deterministic — no run-to-run variance. `scripts/measure_bloom_fpr.py` | rigor signal: the implementation matches `(1-e^(-kn/m))^k` |
| Bloom filter memory vs hash set | 4 | **117 KiB vs 11.3 MiB (99x reduction)** at 100k URLs; 9.59 bits/element at 1% target FPR | why the data structure exists |
| Duplicate pages caught | 4 | Exact content dedup catches same-text-different-URL mirrors (verified end to end: a mirrored page in the API test corpus is fetched but not indexed). Near-duplicates (SimHash territory) are out of scope, documented | dedup effectiveness |
| Speedup from intersecting smallest list first | 7 | **1.3–1.4x** on a 3-term AND (df 20 / 1,554 / 19,056; smallest-first 1.11 ms vs largest-first 1.53 ms, medians of 3). Honest caveat: a two-pointer merge scans both lists regardless, so fold order only shrinks the *intermediate* — the big win needs galloping/skip-pointer intersection (documented as the upgrade, not built). `scripts/bench_query.py` | algorithmic optimization |
| Peak memory at N pages | 9 | **40.4 MB peak RSS** crawling 1,000 pages (8 workers, includes interpreter + test server). Index build: 186.7 MB at 20k docs (see corpus-vs-index row) | resource discipline |
