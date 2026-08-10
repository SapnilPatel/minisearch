-- minisearch database schema.
--
-- Not wired into the code yet — the inverted index lives in memory until
-- Milestone 6, at which point this schema becomes its durable backing store so
-- that restarting the process does not throw away a crawl.
--
-- Apply with:  psql minisearch -f minisearch/store/schema.sql

-- One row per crawled document. Extracted text is stored (not just indexed)
-- because snippet generation at query time needs the original words.
CREATE TABLE IF NOT EXISTS documents (
    id           BIGSERIAL PRIMARY KEY,
    url          TEXT        NOT NULL UNIQUE,   -- canonical (normalized) URL
    title        TEXT,
    text         TEXT        NOT NULL,          -- extracted body text (for snippets)
    content_hash BYTEA       NOT NULL,          -- hash of extracted text, for dedup
    length       INTEGER     NOT NULL,          -- token count; BM25 needs per-doc length
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The term dictionary. doc_frequency (how many documents contain the term) is
-- denormalized here because BM25's IDF needs it on every query.
CREATE TABLE IF NOT EXISTS terms (
    id            BIGSERIAL PRIMARY KEY,
    term          TEXT    NOT NULL UNIQUE,
    doc_frequency INTEGER NOT NULL DEFAULT 0
);

-- The posting lists, one row per (term, document) pair.
-- Composite PK (term_id, doc_id): a term appears in a document at most once as a
-- posting, and this ordering makes "all docs for a term" a contiguous scan —
-- which is exactly the access pattern the query engine needs.
CREATE TABLE IF NOT EXISTS postings (
    term_id   BIGINT  NOT NULL REFERENCES terms(id)     ON DELETE CASCADE,
    doc_id    BIGINT  NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    tf        INTEGER NOT NULL,        -- term frequency within the document
    positions INTEGER[] NOT NULL,      -- token offsets, for phrase queries
    PRIMARY KEY (term_id, doc_id)
);

-- Durable crawl frontier so an interrupted crawl can resume where it left off.
CREATE TABLE IF NOT EXISTS crawl_queue (
    url             TEXT        PRIMARY KEY,   -- canonical URL
    host            TEXT        NOT NULL,
    priority        INTEGER     NOT NULL DEFAULT 0,
    state           TEXT        NOT NULL DEFAULT 'pending',  -- pending|fetching|done|failed
    attempts        INTEGER     NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Pop-the-next-URL query hits (state, next_attempt_at); index it.
CREATE INDEX IF NOT EXISTS idx_crawl_queue_ready
    ON crawl_queue (state, next_attempt_at);

-- Round-robin across hosts needs an efficient by-host lookup.
CREATE INDEX IF NOT EXISTS idx_crawl_queue_host
    ON crawl_queue (host);
