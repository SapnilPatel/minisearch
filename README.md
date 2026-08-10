# minisearch

A concurrent web crawler and search engine in Python: crawl pages politely,
build an inverted index, rank results with **BM25**, serve queries over a REST
API — with the core data structures **hand-rolled** and the performance claims
**measured**.

```
$ curl -X POST localhost:8080/crawl -d '{"seeds": ["https://books.toscrape.com/"], "max_pages": 200, "max_depth": 2}'
{"status": "started", "seeds": 1}

$ curl 'localhost:8080/search?q=historical+fiction'
{"query": "historical fiction", "count": 7, "hits": [
  {"url": "...", "title": "...", "score": 11.2043, "snippet": "… historical fiction …"}, ...]}
```

## What's hand-rolled (deliberately)

| Component | Instead of | Why |
|---|---|---|
| Bloom filter (bit array, k hashes from one BLAKE2b digest) | a hash set / a library | 99× less memory, measured FPR matches `(1−e^(−kn/m))^k` within 2% |
| Mercator frontier (priority front queues, per-host back queues) | a FIFO | priority + politeness + starvation-resistance, separately |
| Inverted index with sorted posting lists + positions | a search library | AND = linear merge; positions enable phrase queries |
| BM25 + bounded top-K min-heap | sorting all matches | O(n log K), O(K) memory |
| Porter stemmer (the 1980 paper, all five steps) | NLTK | 66 test vectors pin the rules |
| robots.txt parser (RFC 9309 longest-match) | stdlib `robotparser` | correct Allow/Disallow ties + Crawl-delay |
| Prometheus metrics registry | prometheus_client | 3 metric types fit in a page of code |

Libraries are used only for plumbing: `aiohttp` (HTTP), `asyncpg` (Postgres
driver), `python-dotenv` (config).

## Measured (Apple M4, details in [METRICS.md](METRICS.md))

- **~7,400 pages/sec** crawl throughput (localhost upper bound), 40 MB peak RSS
- **~3,440 docs/sec** analyze+index
- Query latency: **1.0 ms p50** rare term · **2.6 ms** 2-term AND · **13.5 ms**
  common term (20k-doc index)
- **36×** batched posting inserts vs row-by-row (**56×** with COPY)
- Bloom filter: **1.020% measured vs 1.004% predicted** FPR; **99×** smaller
  than the equivalent hash set

## Architecture

Two independent paths meet at one shared inverted index:

```
ingest:  frontier ─▶ fetcher pool ─▶ dedup ─▶ extract ─▶ analyze ─▶ index ─▶ Postgres
         (priority +  (N workers,     (bloom +  (HTML→     (tokenize,          (durable,
          politeness)  backpressure)   content)  text+links) stem, positions)    batched)

query:   parse ─▶ postings ─▶ intersect ─▶ BM25 ─▶ top-K heap ─▶ snippets
```

The two are coupled only by a **bounded queue**: a slow indexer fills it,
fetchers block, the crawl self-throttles. Design rationale and trade-offs for
every component: [DESIGN.md](DESIGN.md).

## Safety / politeness

The crawler refuses any host not on the `ALLOWED_DOMAINS` allowlist —
re-checked on **every redirect hop** — respects robots.txt (RFC 9309
semantics) and Crawl-delay, enforces true per-host concurrency 1 (the host
stays locked while its fetch is in flight), and sends an identifying
User-Agent.

## Quickstart

Requires Python 3.11+; PostgreSQL optional (queries and crawling work
in-memory without it).

```bash
python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
pytest -q                                   # 215 tests

cp .env.example .env                        # set ALLOWED_DOMAINS etc.
minisearch                                  # serve on :8080
```

With Postgres (crawls survive restarts):

```bash
brew install postgresql@16 && brew services start postgresql@16
createdb minisearch
psql minisearch -f minisearch/store/schema.sql
minisearch                                  # picks up DATABASE_URL, restores index
```

## API

| Endpoint | Description |
|---|---|
| `POST /crawl` | `{"seeds": [...], "max_pages": N, "max_depth": D}` → 202 (409 if one is running) |
| `GET /search?q=...&limit=10` | BM25-ranked hits with snippets. Phrases: `q="machine learning"`; union: `a OR b` |
| `GET /stats` | documents, terms, dedup counts, last-crawl summary |
| `GET /metrics` | Prometheus text format |
| `GET /healthz` | liveness |

## Benchmarks

```bash
python scripts/bench_crawl.py 1000 8        # crawl throughput + peak RSS
python scripts/measure_bloom_fpr.py         # measured vs theoretical FPR
python scripts/bench_inserts.py 5000        # batch vs row-by-row vs COPY
python scripts/bench_query.py 20000         # index rate, latency p50/p99, fold order
```

## Documents

- [DESIGN.md](DESIGN.md) — every decision, its alternative, and what I'd change
- [METRICS.md](METRICS.md) — the measurements behind every number above
- [BUGLOG.md](BUGLOG.md) — bugs hit during the build and how they were found
- [SPEC.md](SPEC.md) — the original design specification

## License

[MIT](LICENSE)
