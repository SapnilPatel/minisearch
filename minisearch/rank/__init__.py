"""Ranking — BM25 (Milestone 7).

Scores each matching document against the query. BM25 saturates term frequency,
normalizes by document length, and weights rare terms higher via IDF. Top-K is
selected with a bounded min-heap, not a full sort of all matches."""
