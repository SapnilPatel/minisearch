# minisearch

A concurrent web crawler and search engine in Python: crawl pages, build an
inverted index, rank results with **BM25**, and serve queries over a REST API.

It is built to demonstrate the parts of backend engineering that a
general-purpose CRUD app never touches — classic data structures, ranking
algorithms, real concurrency with backpressure, database design, and measured
performance. The core structures (bloom filter, priority frontier, inverted
index, BM25, Porter stemmer) are **hand-rolled**, not pulled from a library.

> Status: **Milestone 0 — scaffold.** The pipeline described below is being built
> milestone by milestone (see [SPEC.md](SPEC.md)). Components not yet implemented
> are present as documented stub packages.

## Architecture

Two independent paths run through one shared inverted index:

- **Ingest:** frontier → fetch → dedup → extract → analyze → index
- **Query:** parse → look up posting lists → intersect → score (BM25) → top-K

```
POST /crawl ─▶ Frontier ─▶ Fetcher pool ─▶ Dedup ─▶ Extractor ─▶ Analyzer ─▶ Inverted Index ─▶ PostgreSQL
                (heap +      (N workers,    (bloom    (HTML→text   (tokenize,      ▲
                 politeness)  backpressure)  filter)   + links)     stem, positions)│
                                                                                    │
GET /search ─▶ Query engine ─▶ posting-list intersection ─▶ BM25 ─▶ top-K ──────────┘
```

## Layout

| Path | Component | Milestone |
|---|---|---|
| `minisearch/urls/` | URL canonicalization | 1 |
| `minisearch/robots/` | robots.txt parser + cache | 1 |
| `minisearch/frontier/` | priority-heap URL queue with politeness | 2 |
| `minisearch/fetcher/` | bounded async worker pool | 3 |
| `minisearch/dedup/` | bloom filter + content hashing | 4 |
| `minisearch/extract/` | HTML → text and links | 5 |
| `minisearch/analyze/` | tokenize, stopwords, stemming | 5 |
| `minisearch/index/` | inverted index + posting lists | 6 |
| `minisearch/store/` | PostgreSQL persistence (`schema.sql`) | 6 |
| `minisearch/query/` | query engine | 7 |
| `minisearch/rank/` | BM25 + top-K selection | 7 |
| `minisearch/api/` | REST endpoints | 8 |
| `minisearch/metrics/` | Prometheus instrumentation | 8 |

## Quickstart

Requires Python 3.11+.

```bash
# 1. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 2. Install the project with dev tooling
pip install -e ".[dev]"

# 3. Run the tests
pytest -q

# 4. (Optional) copy the config template and edit it
cp .env.example .env
```

Postgres (Milestone 6+) runs locally via Homebrew:

```bash
brew install postgresql@16
brew services start postgresql@16
createdb minisearch
psql minisearch -f minisearch/store/schema.sql
```

## Development

```bash
ruff check .     # lint
pytest -q        # test
```

CI runs both on every push and pull request (`.github/workflows/ci.yml`).

## Documents

- [SPEC.md](SPEC.md) — the full design specification and milestone plan.
- [METRICS.md](METRICS.md) — measured performance numbers, recorded per milestone.
- [BUGLOG.md](BUGLOG.md) — running journal of bugs hit and how they were found.

## License

[MIT](LICENSE)
