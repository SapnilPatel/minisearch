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
| Machine | (TBD — record CPU / RAM / OS on first benchmark) |
| Python | 3.13 |

## Results

| Metric | Milestone | Value | Notes |
|---|---|---|---|
| Pages crawled/sec | 3 | — | headline throughput |
| Documents indexed/sec | 6 | — | ingest performance |
| Batch vs row-by-row insert speedup | 6 | — | DB optimization |
| Query latency p50 / p99 | 7 | — | the SDE headline number |
| Corpus size vs index size | 6 | — | storage efficiency |
| Bloom filter FPR: measured vs theoretical | 4 | — | rigor signal |
| Duplicate pages caught | 4 | — | dedup effectiveness |
| Speedup from intersecting smallest list first | 7 | — | algorithmic optimization |
| Peak memory at N pages | 9 | — | resource discipline |
