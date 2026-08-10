"""Content-hash deduplication.

The bloom filter answers "have I seen this URL?"; this answers the *other*
question — "have I seen this content under a different URL?" (mirrors, tracking
variants that survived canonicalization, `/print` views, ...). Exact hashes, not
a bloom filter: false positives here would silently drop legitimate distinct
pages from the index, and a digest set costs only 16 bytes per unique page.

Wired into the pipeline after the extractor (Milestone 5) — dedup runs on
extracted *text*, not raw HTML, so trivial markup differences (ads, timestamps
in comments) don't defeat it. Exact matching still misses near-duplicates; the
classic upgrade is SimHash/MinHash shingling, deliberately out of scope and
noted here as the known limitation.
"""

from __future__ import annotations

from hashlib import blake2b


class ContentDeduper:
    __slots__ = ("_digests", "_duplicates")

    def __init__(self) -> None:
        self._digests: set[bytes] = set()
        self._duplicates = 0

    def seen_before(self, url: str, text: str) -> bool:
        """Record ``text``; return True if identical text was already seen.

        ``url`` is accepted for symmetry/logging but does not affect the answer —
        content identity is decided by the text alone.
        """
        digest = blake2b(text.encode("utf-8"), digest_size=16).digest()
        if digest in self._digests:
            self._duplicates += 1
            return True
        self._digests.add(digest)
        return False

    @property
    def stats(self) -> dict[str, int]:
        return {"unique": len(self._digests), "duplicates": self._duplicates}
