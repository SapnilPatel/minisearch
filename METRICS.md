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
| Documents indexed/sec | 6 | — | ingest performance |
| Batch vs row-by-row insert speedup | 6 | — | DB optimization |
| Query latency p50 / p99 | 7 | — | the SDE headline number |
| Corpus size vs index size | 6 | — | storage efficiency |
| Bloom filter FPR: measured vs theoretical | 4 | — | rigor signal |
| Duplicate pages caught | 4 | — | dedup effectiveness |
| Speedup from intersecting smallest list first | 7 | — | algorithmic optimization |
| Peak memory at N pages | 9 | — | resource discipline |
