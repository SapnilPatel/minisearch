# CLAUDE.md

Context for AI assistants (and humans) working on this repo across sessions.

## What this is

`minisearch` — a concurrent web crawler + search engine in **Python**, built
milestone by milestone from [SPEC.md](SPEC.md). It is a portfolio/interview
project: the goal is code the author can **defend line by line**, not code that
merely works. Favor clarity and explainability over cleverness.

## Non-negotiable principles

1. **Hand-roll the core.** The bloom filter, priority frontier, inverted index,
   BM25 scorer, top-K min-heap, and Porter stemmer are implemented from scratch.
   Do **not** reach for a library that does these — that is the entire point.
   Libraries are fine for plumbing (HTTP, DB driver, config).
2. **Tests before implementation**, every milestone. A milestone is not done
   until tests pass and the author can explain the design and its alternatives.
3. **Measure, don't guess.** Record real numbers in [METRICS.md](METRICS.md):
   run each benchmark ≥3 times, report a representative run with spread, and
   measure memory, not just speed.
4. **Be a good crawler citizen.** Respect robots.txt, honor Crawl-delay, keep
   per-host concurrency at 1, send an honest User-Agent, and never fetch a host
   outside `ALLOWED_DOMAINS` (see `minisearch/config.py`).
5. **Keep the two paths separate** in your head and in the code: the ingest path
   and the query path share only the inverted index.

## Stack decisions

- **Language:** Python (asyncio/aiohttp). Chosen over the spec's Go suggestion.
  Concurrency story = bounded `asyncio.Queue` for backpressure + per-host
  `asyncio.Semaphore` for politeness + task cancellation for graceful shutdown.
- **Database:** local Homebrew PostgreSQL (not Docker). Schema in
  `minisearch/store/schema.sql`; in-memory until Milestone 6.
- **Test/lint:** pytest (+ pytest-asyncio, `asyncio_mode=auto`) and ruff.

## Layout

One subpackage per pipeline component; each `__init__.py` docstring names the
milestone that fills it. See the table in [README.md](README.md).

## Workflow per milestone

1. Plan first — explain the approach and the alternatives, then wait for sign-off.
2. Write tests, then implementation.
3. Run `ruff check .` and `pytest -q` — both must be green.
4. Commit with a descriptive message; push. Record any metrics and bugs.

## Commands

```bash
python3 -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
ruff check .
pytest -q
```

Note: the venv is `venv/`, deliberately NOT `.venv/` — macOS keeps re-applying
the `hidden` file flag to dot-named directories here, and Python 3.13 skips
hidden `.pth` files, which silently breaks the editable install (see BUGLOG.md).
