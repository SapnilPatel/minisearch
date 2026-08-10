# Design decisions

Each component: what was chosen, why, what the alternative was, and — where
honest — what should change next. Measured claims reference [METRICS.md](METRICS.md).

## Language: Python + asyncio

**Chosen:** Python 3.13, asyncio/aiohttp, hand-rolled core data structures.
**Alternative:** Go (the spec's suggestion — goroutines, `container/heap`).
**Why:** zero language-learning overhead for the author; the architecture is
identical. The concurrency story maps one-to-one: bounded `asyncio.Queue` ↔
bounded channels, per-host locking in the frontier ↔ per-host goroutine
budget, task cancellation ↔ context cancellation. The cost is honest: single
CPU core (the GIL never bites because the workload is I/O-bound, but CPU-bound
indexing shares one core) and higher memory per object (measured: the index is
8.6× its corpus; a packed Go implementation would be far tighter).

## URL frontier: Mercator two-level queues

**Chosen:** front queues per priority level (depth), per-host back queues with
a min-heap of `next_allowed_time` (Manning & Schütze ch. 20; the Mercator
design).
**Alternative:** one global priority heap with politeness deferral — simpler,
but fairness then depends on the politeness delay being large, and a flooding
host can dominate the heap.
**Key decision made under way:** the pop/host_done protocol. Rescheduling a
host at *pop* time only rate-limits request starts; a response slower than the
delay allows two in-flight requests to one host. Locking the host until the
caller reports completion is what actually enforces per-host concurrency 1
(BUGLOG, M3). The politeness clock counts from completion, not start.
**Deliberate deviation:** front-queue selection is strictly highest-priority-
first, not randomized as in production Mercator — chosen for deterministic
tests; the trade-off (possible starvation of low-priority queues in a
long-running crawl) is accepted and documented.

## URL dedup: hand-rolled bloom filter

**Chosen:** bit array + k hashes derived from one 128-bit BLAKE2b digest via
Kirsch–Mitzenmacher double hashing; sized by `m = −n·ln p/(ln 2)²`,
`k = (m/n)·ln 2`.
**Alternative:** a hash set of every URL — exact, but stores the strings:
measured 99× more memory at 100k URLs.
**Why safe:** the failure asymmetry. False positive = skip one never-seen page
(bounded, tunable: measured 1.02% vs 1.00% theoretical at design load). False
negative = impossible, bits are never cleared — so the crawler can never loop.
**Why BLAKE2b, not `hash()`:** Python's builtin is salted per process; a
persisted filter would silently forget everything on restart.

## Content dedup: exact digest set (not a bloom filter)

Same question, different failure cost: a false positive here would silently
drop a legitimate page from the index. So: exact BLAKE2b digests, 16 bytes per
unique page. Runs on extracted *text*, not raw HTML, so markup noise can't
defeat it. Known limitation: near-duplicates need SimHash/MinHash shingling —
out of scope, named.

## Fetcher pool: bounded queue = backpressure

**Chosen:** N workers over the shared frontier; results flow through a
*bounded* `asyncio.Queue`; the hand-off happens inside the frontier's host
lock.
**Why the bound is the design:** if the indexer (or its DB writes) falls
behind, `put` blocks, workers stall, the crawl self-throttles. No unbounded
buffer of HTML in RAM, and the politeness clock slows with the consumer.
**Retry policy:** exponential backoff with full jitter on 5xx/429 and network
errors (jitter prevents retry stampedes against a struggling host); hard 4xx
fails fast. Redirects are followed manually so the allowlist and robots checks
re-run on *every hop* — a redirect can cross onto a host you must not fetch.
**Shutdown:** stop() lets in-flight work complete and deliver; tested that
`fetched == delivered` with no hang.

## robots.txt: hand-rolled parser

**Chosen:** RFC 9309 semantics — longest-match wins, Allow beats Disallow on
ties, `*`/`$` patterns, Crawl-delay.
**Alternative:** stdlib `robotparser` — gets longest-match wrong and ignores
Crawl-delay.
**Fail-open on 4xx/unreachable** (allowed): the hard safety rail is the domain
allowlist, not robots; Google's 5xx-means-disallow is a defensible
alternative, noted inline.

## Inverted index: sorted-by-construction posting lists

**Chosen:** `term -> [(doc_id, tf, positions)]` with doc ids assigned
ascending at add time, so every list is sorted with zero sort calls, ever.
AND queries are then linear two-pointer merges.
**Positions stored** (space cost accepted) to enable phrase queries; positions
index the original token stream, so stopwords keep their slot — the documented
consequence is that phrases spanning a stopword ("state of the art") cannot
exact-match.
**Honest measurement:** the index is 8.6× its corpus in memory — Python object
overhead per posting. The known fix is packed, delta-encoded postings
(doc-id gaps + varint), which would also enable skip pointers. Documented,
not built.

## Persistence: PostgreSQL, one transaction per document

**Chosen:** in-memory index serves queries; Postgres makes crawls durable.
Each document commits atomically (doc row + term upserts + postings), so an
interrupted crawl leaves no half-indexed document — restart loads the index
and continues with the next doc id.
**The measured claim:** batching posting inserts is 36× row-by-row
(executemany in one transaction), 56× with COPY. Row-by-row pays a round-trip
plus a WAL fsync per row.
**Composite PK `(term_id, doc_id)`:** a term appears at most once per doc, and
the PK's physical ordering makes "all postings for a term" a contiguous range
scan — exactly the query path's access pattern.

## Ranking: BM25 with the +1 IDF variant

**Chosen:** `IDF = ln(1 + (N − df + 0.5)/(df + 0.5))` — stays positive when a
term appears in more than half the corpus (raw Robertson IDF goes negative
there, which poisons AND queries).
**k1 = 1.5, b = 0.75** (literature defaults), both configurable. What they do
is pinned by tests: k1=0 degenerates to binary match; b=0 disables length
normalization.
**Alternative:** TF-IDF — no tf saturation (the 20th occurrence counts like
the 2nd) and no length normalization. BM25 is strictly the better default.

## Top-K: bounded min-heap

O(n log K) time and O(K) memory versus sorting all matches. The root is the
worst of the current best K; candidates below it are rejected in O(1). A
first-run test caught the tie-handling bug (later ties evicted earlier
entries — the sequence tiebreak had accidentally defined policy); fixed by
negating the sequence so ties never evict admitted entries.

## Query engine: fold order and its honest limits

Multi-list AND folds smallest-df-first. Measured: 1.3–1.4× on a 3-term query
with df 20/1.5k/19k. The honest caveat — a two-pointer merge scans both inputs
regardless, so fold order only shrinks intermediates; the real win at extreme
skew needs galloping (exponential-probe binary search) intersection or skip
pointers over packed postings. Next thing to build if this index grew.

Phrase p99 (~180 ms vs 9 ms p50) spikes on position-set construction for
high-df phrase terms — same packed-postings fix applies.

## API: one process, no locks

aiohttp; ingest runs as a background producer/consumer task pair while
searches read the shared index. Safe without locks because asyncio interleaves
only at await points — stated as an explicit assumption, it would not survive
a move to threads. One crawl at a time (409 otherwise): frontier, bloom
filter, and politeness state are per-crawl.

## Metrics: hand-rolled Prometheus exposition

Three metric types and a text format fit in a page of code; a dependency
wasn't justified. Single-threaded event loop ⇒ no locking on updates — same
explicit assumption as above.

## What I would do differently

1. **Packed postings** (delta + varint in `bytes`): fixes the 8.6× memory
   ratio, the phrase p99, and unlocks skip pointers/galloping — one change,
   three wins.
2. **Randomized front-queue selection** for long-running crawls (the
   determinism trade-off flips outside tests).
3. **Persist the frontier + bloom filter** so an interrupted *crawl* (not just
   the index) resumes — the schema's `crawl_queue` table is ready for it.
4. **SimHash** for near-duplicate detection.
