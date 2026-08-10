"""The fetcher pool — bounded concurrency (Milestone 3).

N async workers pull from the frontier and issue HTTP GETs over bounded channels,
giving natural backpressure: if the indexer falls behind, the channel fills and
fetchers block instead of accumulating an unbounded backlog. Handles timeouts,
retry with exponential backoff, robots.txt, max page size, and graceful shutdown."""
