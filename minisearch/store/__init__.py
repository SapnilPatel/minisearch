"""Persistence — PostgreSQL (Milestone 6).

Documents, term dictionary, posting lists, and corpus statistics (doc count and
average length, both needed by BM25). Posting inserts are batched inside a
transaction. See schema.sql for the table layout."""
