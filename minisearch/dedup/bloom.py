"""A hand-rolled bloom filter.

**Why not a hash set?** A set of every URL ever seen stores the URLs themselves —
hundreds of bytes each, unbounded growth. A bloom filter answers "definitely not
seen" / "probably seen" in constant space: ~9.6 bits (1.2 bytes) per element at a
1% false-positive rate, a ~100x memory reduction. The asymmetry is what makes it
safe for crawling: a false positive skips a page we never fetched (bounded,
tunable loss); a false *negative* is impossible, because bits are only ever set,
never cleared — so we can never re-crawl forever.

**Sizing.** For n expected items and target false-positive rate p:

    m = -n * ln(p) / (ln 2)^2     bits
    k = (m / n) * ln 2            hash functions

and the expected FPR after inserting n items is (1 - e^(-k*n/m))^k, which
``theoretical_fpr`` computes so measurements can be checked against theory
(see scripts/measure_bloom_fpr.py and METRICS.md).

**Hashing.** k independent hashes are derived from ONE 128-bit BLAKE2b digest
via the Kirsch–Mitzenmacher double-hashing construction:

    h_i(x) = (h1(x) + i * h2(x)) mod m

which provably preserves the bloom filter's FPR guarantees while hashing each
item once instead of k times. BLAKE2b rather than Python's builtin ``hash()``
because the builtin is salted per process — a persisted filter would silently
"forget" everything on restart.
"""

from __future__ import annotations

import math
from hashlib import blake2b


class BloomFilter:
    __slots__ = ("_bits", "_count", "_k", "_m")

    def __init__(self, expected_items: int, target_fpr: float) -> None:
        if expected_items <= 0:
            raise ValueError("expected_items must be positive")
        if not 0.0 < target_fpr < 1.0:
            raise ValueError("target_fpr must be in (0, 1)")

        m = math.ceil(-expected_items * math.log(target_fpr) / (math.log(2) ** 2))
        self._m = ((m + 7) // 8) * 8          # round up to whole bytes
        self._k = max(1, round((self._m / expected_items) * math.log(2)))
        self._bits = bytearray(self._m // 8)
        self._count = 0                        # items added (for FPR estimates)

    # -- core ----------------------------------------------------------------

    def add(self, item: str) -> None:
        for pos in self._positions(item):
            self._bits[pos >> 3] |= 1 << (pos & 7)
        self._count += 1

    def __contains__(self, item: str) -> bool:
        return all(
            self._bits[pos >> 3] & (1 << (pos & 7)) for pos in self._positions(item)
        )

    def _positions(self, item: str):
        digest = blake2b(item.encode("utf-8"), digest_size=16).digest()
        h1 = int.from_bytes(digest[:8], "big")
        # Force h2 odd: m is a multiple of 8, so an odd h2 is coprime with m,
        # guaranteeing the k probe positions don't collapse onto few slots.
        h2 = int.from_bytes(digest[8:], "big") | 1
        m = self._m
        return ((h1 + i * h2) % m for i in range(self._k))

    # -- introspection -------------------------------------------------------

    def __len__(self) -> int:
        """Number of items added (exact — we count adds, we don't estimate)."""
        return self._count

    @property
    def num_bits(self) -> int:
        return self._m

    @property
    def num_hashes(self) -> int:
        return self._k

    @property
    def size_bytes(self) -> int:
        return len(self._bits)

    @property
    def bits(self) -> bytes:
        return bytes(self._bits)

    def theoretical_fpr(self, items: int | None = None) -> float:
        """Predicted FPR after ``items`` insertions (default: actual count)."""
        n = self._count if items is None else items
        if n == 0:
            return 0.0
        return (1.0 - math.exp(-self._k * n / self._m)) ** self._k
