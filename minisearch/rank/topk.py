"""Top-K selection with a bounded min-heap.

"How do you get the top 10 without sorting all matches?" — keep a heap of at
most K entries whose *minimum* is at the root. For each candidate: if the heap
is short, push (O(log K)); otherwise compare against the root — the worst of
the current best K — and replace it only if the candidate beats it. Candidates
below the root are rejected in O(1), which is the common case once the heap
warms up.

Cost: O(n log K) time, O(K) memory, versus O(n log n) time and O(n) memory for
sort-everything. For n matches in the millions and K=10, that is the difference
that matters.
"""

from __future__ import annotations

import heapq
from typing import TypeVar

T = TypeVar("T")


class TopK:
    """Collect (score, item) pairs; return the K best, highest score first."""

    def __init__(self, k: int) -> None:
        if k <= 0:
            raise ValueError("k must be positive")
        self._k = k
        # Entries are (score, -seq, item). The tiebreak keeps comparisons from
        # ever reaching `item` (so items need not be comparable) and is NEGATED
        # so that on equal scores a later arrival compares as *worse*: a tie
        # must not evict an already-admitted entry, and among admitted ties the
        # later one is evicted first. (The unnegated version failed exactly
        # that test: every new tie displaced the oldest one.)
        self._heap: list[tuple[float, int, T]] = []
        self._seq = 0

    def offer(self, score: float, item: T) -> None:
        entry = (score, -self._seq, item)
        self._seq += 1
        if len(self._heap) < self._k:
            heapq.heappush(self._heap, entry)
        elif entry > self._heap[0]:
            heapq.heapreplace(self._heap, entry)
        # else: worse than the current K-th best — O(1) rejection.

    def results(self) -> list[tuple[float, T]]:
        """The collected best, highest score first (ties: first-offered first)."""
        # Sorting K items is O(K log K) with K small — not the n log n we avoided.
        ordered = sorted(self._heap, key=lambda e: (-e[0], -e[1]))  # seq ascending
        return [(score, item) for score, _seq, item in ordered]
