"""URL canonicalization (Milestone 1).

Normalizes URLs to a single canonical form so dedup works and the same page is
not crawled under many spellings: lowercase host, strip default ports, remove
fragments, resolve relative paths, sort query params, drop tracking params, and
apply a consistent trailing-slash policy.
"""

from minisearch.urls.canonical import TRACKING_PARAMS, canonicalize

__all__ = ["TRACKING_PARAMS", "canonicalize"]
