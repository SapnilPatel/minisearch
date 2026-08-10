"""The query engine (Milestone 7).

Parses the query, fetches posting lists, intersects (AND) or unions (OR) them,
scores with BM25, and returns the top K with snippets. Supports single terms,
multi-term AND/OR, and phrase queries using stored positions."""
