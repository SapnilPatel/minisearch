# minisearch — Design Specification

A concurrent web crawler and search engine in Go: crawl pages, build an
inverted index, rank with BM25, serve queries over a REST API.

This document is the plan. Hand it to Claude Code and work through it milestone
by milestone. It is written to be read by both you and the tool.

---

## Part 1 — Why this project, and who it is for

### The gap it closes

Your resume currently proves: LLM inference serving, RL, evaluation pipelines,
agent orchestration, ML infrastructure. It is a strong **AI Engineer** profile.

What it does *not* prove, in any bullet:

| Gap | Currently | After this project |
|---|---|---|
| Databases used in real work | Listed in Skills only | PostgreSQL schema, transactions, query tuning |
| API design | Implied by FastAPI | REST API you designed and documented |
| Automated testing | Nothing anywhere | Unit + integration suites in CI |
| Classic data structures | Coursework line only | Heap, bloom filter, inverted index, posting lists |
| Algorithms | Coursework line only | BM25 ranking, sorted-set intersection, top-K selection |
| Concurrency you wrote | Nothing | Worker pool, bounded channels, backpressure, graceful shutdown |

Six holes, one project.

### Who it is for — in priority order

**1. Google — Software Engineer, Early Career, Campus (primary target)**

This project was chosen against that specific job description:

- *"Experience working with data structures or algorithms"* — **minimum
  qualification.** This project is dense in both: a priority-queue frontier, a
  bloom filter, an inverted index with posting lists, BM25 scoring, top-K
  selection via min-heap. This is the single strongest reason to build it.
- *"Software development in one or more programming languages"* — **minimum
  qualification.** Go is Google's own language.
- *"information retrieval"* — named **preferred qualification.** Nothing else
  you could build hits this. A search engine *is* information retrieval.
- *"distributed and parallel systems"* — preferred. The fetcher pool covers
  parallel; the optional sharding milestone covers distributed.
- *"Unix/Linux environments"* — preferred. Runs and is benchmarked on Linux.

And there is a soft advantage worth naming: search is Google's founding
problem. An interviewer there will have opinions about your ranking function.
That is a conversation you want, not one you should avoid.

**2. Meta, Amazon, Microsoft, Apple — SDE new grad (secondary)**

Nothing here is Google-specific. Concurrency, storage, API design, and
measured performance are the universal backend signals. "Design a web crawler"
is also a standard system design interview question — building one means you
have implemented what you may later be asked to design.

**3. AI/ML Engineer roles (tertiary, via Milestone 10)**

The stretch milestone adds embedding-based semantic search alongside keyword
BM25, with a measured comparison between them. That turns this into a
hybrid-retrieval project, which is directly relevant to RAG work and connects
to your existing Pinecone and LLM experience. One build, both targets.

### Why not something else

- **A distributed task queue** covers databases and distributed systems
  slightly better, and is the stronger choice for big tech *generally*. It
  loses on the two things that decide your case: it has far less
  data-structure and algorithm content, and it does not touch information
  retrieval.
- **A custom database engine** is excellent engineering signal but the domain
  would be entirely unfamiliar to you — the same problem that made the HTTP
  server hard to own.
- **Anything CRUD-shaped** is actively dismissed by engineers at these
  companies. Avoided deliberately.

### Why Go

- Created and heavily used at Google — direct signal for the primary target.
- Concurrency is the language's headline feature. Goroutines and channels make
  the worker-pool story natural to build *and* natural to explain.
- Dramatically easier to read and learn than C++. You can be comfortable in Go
  within days, which matters because **you have to be able to defend every line
  of this.**
- Excellent standard library for exactly this project: `net/http`,
  `encoding/json`, `sync`, `context`, `container/heap`.

*If you prefer Python:* the architecture below is unchanged. Substitute
`asyncio` + `aiohttp` for goroutines, `heapq` for `container/heap`, and
`pytest` for `go test`. You lose some SDE signal (Python reads as scripting to
a Google reviewer) and gain zero language-learning overhead. Your call, but Go
is the better trade for this target.

---

## Part 2 — Architecture

```
   POST /crawl                                        GET /search?q=...
        │                                                     │
        ▼                                                     ▼
  ┌──────────┐                                        ┌──────────────┐
  │ Frontier │  priority heap + per-host politeness    │ Query Engine │
  └────┬─────┘                                        └──────┬───────┘
       │ URLs                                                │ posting lists
       ▼                                                     │
  ┌─────────────────────────────┐                            │
  │      Fetcher Pool           │  N goroutines              │
  │  robots.txt · rate limit    │  bounded channels          │
  │  timeouts · retry+backoff   │  backpressure              │
  └────┬────────────────────────┘                            │
       │ raw HTML                                            │
       ▼                                                     │
  ┌──────────┐   seen?    ┌──────────────┐                   │
  │  Dedup   │◄──────────►│ Bloom filter │                   │
  │          │            │ content hash │                   │
  └────┬─────┘            └──────────────┘                   │
       │ new pages                                           │
       ▼                                                     │
  ┌──────────┐  outlinks ──────────► back to Frontier         │
  │ Extractor│                                                │
  │ HTML→text│                                                │
  └────┬─────┘                                                │
       │ text                                                 │
       ▼                                                     │
  ┌──────────┐         ┌───────────────────────────┐          │
  │ Analyzer │────────►│      Inverted Index       │◄─────────┘
  │ tokenize │         │  term → [(docID, tf, pos)]│
  │ stopwords│         └─────────────┬─────────────┘
  │ stemming │                       │
  └──────────┘                       ▼
                          ┌────────────────────┐
                          │    PostgreSQL      │
                          │ documents · terms  │
                          │ postings · stats   │
                          └────────────────────┘
```

Two independent paths through one shared index: an **ingest path** (frontier →
fetch → dedup → extract → analyze → index) and a **query path** (parse → look
up postings → intersect → score → top-K). Keeping them mentally separate is
the key to explaining this system.

---

## Part 3 — Components

For each: what it does, why it exists, and what an interviewer will ask.

### 1. Frontier — the URL queue

**What.** Holds URLs waiting to be crawled. Pops the next URL that is both
highest-priority and allowed by politeness rules.

**Why it is not just a queue.** Two competing requirements. You want to crawl
important pages first (priority), and you must not hammer one host with
concurrent requests (politeness). A plain FIFO gives you neither.

**Structure.** A min-heap keyed by score (shallower depth = higher priority),
plus a per-host map holding `nextAllowedTime`. Pop from the heap; if that
URL's host is not yet allowed, defer it and try the next.

**Data structure content:** binary heap, `container/heap`, hash map.

**Interviewer will ask:** "What if one host dominates the frontier?" (answer:
per-host queues with round-robin, so a single slow host cannot starve others —
implement this, don't just say it). "How do you bound memory if the frontier
grows unboundedly?"

### 2. Fetcher pool — concurrency

**What.** N worker goroutines pulling from the frontier, issuing HTTP GETs,
handing results downstream over a channel.

**Why a bounded pool.** Unbounded goroutines would exhaust file descriptors
and memory, and would violate politeness. A fixed pool with **bounded
channels** gives you natural backpressure: if the indexer falls behind, the
channel fills, fetchers block, and the crawl self-throttles instead of
accumulating an unbounded backlog in RAM.

**Must handle.** Per-request timeouts (`context.WithTimeout`), retry with
exponential backoff on 5xx and network errors, `robots.txt` fetch and cache
per host, Crawl-delay respect, a `User-Agent` identifying your crawler,
maximum page size, and graceful shutdown draining in-flight work.

**Concurrency content:** worker pool, bounded channels, `context` cancellation,
`sync.WaitGroup`, graceful shutdown.

**Interviewer will ask:** "How do you shut down cleanly mid-crawl without
losing or duplicating work?" "What happens when the indexer is slower than the
fetchers?"

**Be a good citizen.** Respect `robots.txt`, set a real User-Agent, keep
per-host concurrency at 1 with a delay. Crawl your own test site and a small
number of crawl-friendly domains. This is both correct and something an
interviewer will notice you thought about.

### 3. Dedup — bloom filter + content hashing

**What.** Two separate questions. *Have I seen this URL?* (bloom filter over
normalized URLs.) *Have I seen this content before under a different URL?*
(hash of the extracted text.)

**Why a bloom filter.** At scale, a hash set of every URL seen does not fit in
memory. A bloom filter answers "definitely not seen" or "probably seen" in
constant space and time, accepting a tunable false-positive rate. A false
positive means you skip a page you have not crawled — an acceptable loss for
the memory saving. A false *negative* is impossible, which is the property
that makes it safe here.

**Do this:** implement the filter yourself (bit array + k hash functions
derived from one 64-bit hash), then **measure the actual false-positive rate
against the theoretical `(1 - e^(-kn/m))^k`**. Reporting measured-vs-predicted
FPR is the kind of detail that separates rigor from box-ticking.

**Data structure content:** bloom filter, bit manipulation, hash functions.

**Interviewer will ask:** "Why not a hash set?" "What is your false positive
rate and how did you choose m and k?" "What breaks if you get a false
positive?"

### 4. Extractor — HTML to text and links

**What.** Parse HTML, pull out title, body text, and outbound links. Normalize
each link to a canonical absolute URL.

**Why normalization is its own problem.** `example.com/a`,
`example.com/a/`, `EXAMPLE.com/a`, `example.com/a#section`, and
`example.com/a?b=1&c=2` vs `?c=2&b=1` may all be the same page. Without
canonicalization your dedup fails and you crawl the same content repeatedly.

**Rules:** lowercase host, strip default ports, remove fragments, resolve
relative paths, sort query parameters, drop known tracking params, decide a
trailing-slash policy and apply it consistently.

**Interviewer will ask:** "How do you know two URLs are the same page?" This is
a deceptively deep question and having a real answer is a differentiator.

### 5. Analyzer — text to terms

**What.** Turn body text into the terms that go in the index: tokenize on
non-alphanumerics, lowercase, drop stopwords, apply stemming (Porter), record
term frequency and positions.

**Why positions.** Storing positions costs space but enables phrase queries
("machine learning" as a phrase, not two words). Implement it — it is a
concrete tradeoff you chose, and it comes up naturally in discussion.

**Interviewer will ask:** "Why stem?" (recall: *running* should match *run*.)
"What does stemming cost you?" (precision: *universe* and *university* can
collide.)

### 6. Inverted index — the core data structure

**What.** A map from term to a **posting list**: the documents containing that
term, each with term frequency and positions.

```
"epoll"  → [(doc 12, tf 3, pos [4,19,88]), (doc 47, tf 1, pos [2]), ...]
"server" → [(doc 3, tf 8, ...), (doc 12, tf 2, ...), ...]
```

**Why inverted.** A forward index (doc → terms) requires scanning every
document per query. Inverting it makes lookup proportional to the number of
documents containing the term, not the corpus size. This is *the* idea that
makes search possible, and you should be able to explain it in one sentence.

**Keep posting lists sorted by docID.** That makes multi-term AND queries a
linear merge of sorted lists rather than a nested loop — and it enables skip
pointers as an optimization worth measuring.

**Data structure content:** inverted index, sorted posting lists, sorted-set
intersection, optional delta encoding and skip pointers.

**Interviewer will ask:** "How do you intersect two posting lists?" "What if
one term appears in 2 documents and another in 2 million?" (intersect
smallest-first).

### 7. Store — PostgreSQL

**What.** Persistence. Documents and metadata, term dictionary, posting lists,
corpus statistics (document count, average length — BM25 needs both).

**Schema sketch:**

```
documents  (id, url UNIQUE, title, content_hash, fetched_at, length, ...)
terms      (id, term UNIQUE, doc_frequency)
postings   (term_id, doc_id, tf, positions)   -- PK (term_id, doc_id)
crawl_queue(url, host, priority, state, attempts, next_attempt_at)
```

**Why Postgres and not just memory.** Restarting should not throw away a
crawl. And this is the piece that closes the "no database work in any bullet"
gap — schema design, batch inserts, transactions, and index choice are the
things you will be asked about.

**Do this:** batch your posting inserts inside a transaction and **measure the
difference** against row-by-row inserts. The gap will be large. That
measurement is a resume bullet.

**Interviewer will ask:** "Why that primary key?" "How do you handle a crawl
interrupted halfway through?" "What did indexing cost you on write?"

### 8. Ranker — BM25

**What.** Score each matching document for a query, so results come back in a
useful order.

**Why BM25 and not simple term counting.** Raw counts favour long documents
and treat every word as equally informative. BM25 fixes both: it saturates
term frequency (the 20th occurrence adds much less than the 2nd), normalizes
by document length, and weights rare terms higher via inverse document
frequency.

```
score(D,Q) = Σ  IDF(qᵢ) · ( tf(qᵢ,D) · (k₁+1) ) / ( tf(qᵢ,D) + k₁·(1-b+b·|D|/avgdl) )
```

You should be able to explain in plain words what `k₁` and `b` control, and
what happens at their extremes.

**Algorithm content:** BM25, IDF, top-K selection with a bounded min-heap
(keep K items, not a full sort of all matches).

**Interviewer will ask:** "Why not TF-IDF?" "What does b=0 mean?" "How do you
get the top 10 without sorting all matches?"

### 9. Query engine

**What.** Parse the query, fetch posting lists, intersect or union them, score
with BM25, return the top K with snippets.

**Support:** single terms, multi-term AND (default), OR, phrase queries using
the positions you stored, and a snippet showing matched terms in context.

**Interviewer will ask:** "Walk me through a query end to end." Practice this
one out loud; it is the most likely question about this project.

### 10. API and observability

**Endpoints:**

```
POST /crawl    {"seeds": [...], "max_pages": N, "max_depth": D}
GET  /search   ?q=...&limit=10
GET  /stats    → pages crawled, index size, unique terms, cache hit rates
GET  /healthz
GET  /metrics  → Prometheus
```

**Metrics to expose:** pages fetched/sec, frontier depth, fetch error rate by
class, index write throughput, query latency histogram, bloom filter FPR.

**Why it matters.** Instrumentation is what lets you make claims with numbers
later. It is also, as you found on the last project, how you discover that
something is quietly wrong.

---

## Part 4 — Milestones

One session with Claude Code per milestone. Each ends with tests passing and a
commit. Do not move on until the current one is green and you can explain it.

| # | Milestone | Deliverable | Ask Claude Code to explain |
|---|---|---|---|
| 0 | Scaffold | Go module, config, Docker Compose for Postgres, CI skeleton, README stub | project layout conventions in Go |
| 1 | URL normalization + robots.txt | Canonicalizer, robots parser/cache, single-page fetch. **Tests first.** | why each normalization rule exists |
| 2 | Frontier | Priority heap, per-host politeness, bounded size | how `container/heap` works |
| 3 | Fetcher pool | N goroutines, bounded channels, timeouts, retry/backoff, graceful shutdown | goroutines vs threads; what backpressure means here |
| 4 | Dedup | Hand-rolled bloom filter + content hashing, **measured vs theoretical FPR** | the FPR formula, and why false negatives are impossible |
| 5 | Extractor + Analyzer | HTML→text, outlink extraction, tokenizer, stopwords, Porter stemmer | tradeoffs of stemming |
| 6 | Inverted index + Postgres | In-memory index, batch persistence, schema, **batch vs row-by-row measured** | why postings are sorted by docID |
| 7 | Query engine + BM25 | Posting intersection, BM25 scoring, top-K min-heap, phrase queries | the BM25 formula, term by term |
| 8 | REST API + metrics | All endpoints, Prometheus instrumentation | HTTP handler patterns in Go |
| 9 | Benchmarks + docs | Benchmark harness, measured results, README, DESIGN.md | how to benchmark without fooling yourself |
| 10 | *Stretch — pick one* | (a) simplified PageRank as a ranking signal, (b) embedding/semantic search with a measured comparison to BM25, (c) index sharding across processes | — |

**On milestone 10:** (b) is the one that makes this an AI-track project too, and
it plays to your existing strength. (a) is the most Google-flavoured. (c) is
the one that legitimately earns the word "distributed."

**Realistic pace:** milestones 0–9 is roughly 25–40 hours of focused work if
you are reviewing and questioning rather than accepting diffs blindly. Spread
over two to three weeks. That is the honest number.

---

## Part 5 — Metrics to capture

Resume bullets need real measurements. Do not skip this — instrument as you go
and record numbers in a file as you hit each milestone.

| Metric | Where from | Why it matters |
|---|---|---|
| Pages crawled/sec | Milestone 3 | Headline throughput number |
| Documents indexed/sec | Milestone 6 | Ingest performance |
| Batch vs row-by-row insert speedup | Milestone 6 | Concrete DB optimization |
| Query latency p50 / p99 | Milestone 7 | The number SDE reviewers care most about |
| Corpus size vs index size | Milestone 6 | Storage efficiency |
| Bloom filter FPR: measured vs theoretical | Milestone 4 | Rigor signal |
| Duplicate pages caught | Milestone 4 | Dedup effectiveness |
| Speedup from intersecting smallest list first | Milestone 7 | Algorithmic optimization |
| Peak memory at N pages | Milestone 9 | Resource discipline |

Two rules, both learned the hard way on the last project:

1. **Run every benchmark at least three times** and report a representative
   run with the spread, not your best one. Variance is real and an interviewer
   asking "did you run it more than once?" should not catch you out.
2. **Measure memory, not just speed.** Throughput benchmarks reward exactly
   the kind of eager allocation that wrecks memory behaviour, and will never
   tell you about it.

---

## Part 6 — What comes after the build

**Resume bullets.** I will write these once you have real numbers — three
bullets in the XYZ format ("accomplished X as measured by Y by doing Z"), plus
a project title. I am deliberately not drafting them now, because bullets
built on invented metrics fall apart in interviews and there is no point
writing placeholders.

**Interview prep.** Once it is built we will produce:

- A walkthrough script — the two-minute version and the thirty-second version
- The plain-language explanation for non-technical interviewers
- A list of likely questions per component with your answers
- The "what would you do differently" answer, which every loop asks
- A `DESIGN.md` for the repo recording each decision and its alternative

**One thing to do during the build, not after:** keep a running note of every
bug you hit and how you found it. Those stories are the most valuable
interview material you will produce, and they are impossible to reconstruct
later. On the last project the memory regression was worth more than any
throughput number — and it only existed because it was measured and recorded.

---

## Part 7 — Handing this to Claude Code

```bash
mkdir minisearch && cd minisearch
git init
# put this file in the repo as SPEC.md
claude
```

Opening prompt:

> Read SPEC.md. We're building this together over several sessions. I need to
> be able to explain every design decision in an interview, so before writing
> code for a milestone, explain your approach and the alternatives you
> considered, and wait for me to agree. Start with Milestone 0 only.

Then per milestone:

> Milestone N from SPEC.md. Use plan mode first — explain the approach and why,
> then wait. Write tests before implementation. When done, walk me through what
> you wrote.

Run `/init` early to generate a `CLAUDE.md` so project context persists across
sessions. Use `Shift+Tab` for plan mode whenever you want explanation without
changes.

**The rule that decides whether this works:** if you finish a session without
having asked "why did you do it that way" at least three times, you have built
code you cannot defend. The point is not the repo. The point is that you can
stand in front of a whiteboard and derive it again.
