"""The URL frontier — a Mercator-style two-level queue.

This is the design used by production crawlers and described in Manning &
Schütze, *Introduction to Information Retrieval*, ch. 20. It cleanly separates
the two competing requirements instead of trading one against the other:

* **Front queues** implement *priority*. There are F FIFO queues, one per
  priority level; a URL's depth selects its queue (shallower = higher priority).
* **Back queues** implement *politeness*. Each back queue holds URLs for exactly
  one host. A min-heap keyed by each host's ``next_allowed_time`` decides which
  host to fetch from next, so we never issue back-to-back requests to one host.

The router pulls from the front queues (priority-first) to refill an emptied back
queue. A host that floods the frontier cannot starve the others: after each fetch
its back queue is rescheduled to ``now + delay``, so every other due host is
served before it comes around again. That is the concrete answer to the classic
"what if one host dominates the frontier?" question.

**Determinism for testing.** ``pop_ready`` takes an explicit ``now`` (monotonic
seconds) rather than reading the clock, so politeness is testable without
sleeping. Production Mercator also *randomizes* front-queue selection to avoid
starving low-priority queues; we choose strictly highest-priority-first for
determinism and note the trade-off here.
"""

from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass
from urllib.parse import urlsplit

from minisearch.config import Config
from minisearch.urls import canonicalize


@dataclass(frozen=True, slots=True)
class FrontierItem:
    url: str      # canonical URL
    depth: int    # distance from a seed; the priority signal
    host: str


class Frontier:
    """A bounded, polite, priority URL frontier."""

    def __init__(
        self,
        config: Config,
        *,
        front_queues: int = 10,
        back_queues: int | None = None,
    ) -> None:
        self._delay = config.per_host_delay_s
        self._max_size = config.max_frontier_size
        self._front_count = max(1, front_queues)
        # Mercator rule of thumb: keep ~3x as many back queues as fetch workers,
        # so there is always a due host to hand to a free worker.
        self._back_count = back_queues or max(1, config.fetcher_workers * 3)

        # Front queues: index 0 is highest priority.
        self._front: list[deque[FrontierItem]] = [
            deque() for _ in range(self._front_count)
        ]
        # Back queues: host -> its FIFO of URLs. At most _back_count hosts here.
        self._back: dict[str, deque[FrontierItem]] = {}
        # Min-heap of (next_allowed_time, seq, host); one entry per active host.
        self._ready: list[tuple[float, int, str]] = []

        # Dedup of every URL ever enqueued. NOTE: this grows unbounded — exactly
        # the memory problem the Milestone 4 bloom filter replaces it with.
        self._seen: set[str] = set()

        self._seq = 0
        self._size = 0        # total URLs held (front + back)
        self._enqueued = 0
        self._dropped = 0

    # -- public API ---------------------------------------------------------

    def add(self, url: str, depth: int = 0) -> bool:
        """Enqueue a URL. Returns False if it is a duplicate or the frontier is full."""
        canon = canonicalize(url)
        if canon in self._seen:
            return False
        if self._size >= self._max_size:
            self._dropped += 1
            return False

        host = urlsplit(canon).hostname or ""
        bucket = min(max(depth, 0), self._front_count - 1)
        self._front[bucket].append(FrontierItem(url=canon, depth=depth, host=host))
        self._seen.add(canon)
        self._size += 1
        self._enqueued += 1
        return True

    def pop_ready(self, now: float) -> FrontierItem | None:
        """Return the next URL allowed by politeness at ``now``, or None.

        None means either the frontier is empty or every host with queued work is
        still inside its politeness delay — call ``time_until_ready`` to learn how
        long until the next one frees up.
        """
        self._fill(now)
        while self._ready:
            when, _seq, host = self._ready[0]
            if when > now:
                return None  # the earliest-due host is not ready yet
            heapq.heappop(self._ready)
            queue = self._back.get(host)
            if not queue:
                continue  # defensive: skip a stale heap entry
            item = queue.popleft()
            self._size -= 1
            if queue:
                self._reschedule(host, now)  # host has more; wait out the delay
            else:
                del self._back[host]         # host drained; free the slot
                self._fill(now)              # admit a new host in its place
            return item
        return None

    def time_until_ready(self, now: float) -> float | None:
        """Seconds until some host becomes fetchable, or None if the frontier is empty."""
        self._fill(now)
        while self._ready:
            when, _seq, host = self._ready[0]
            if host not in self._back:
                heapq.heappop(self._ready)
                continue
            return max(0.0, when - now)
        return None

    def __len__(self) -> int:
        return self._size

    @property
    def stats(self) -> dict[str, int]:
        return {
            "size": self._size,
            "enqueued": self._enqueued,
            "dropped": self._dropped,
            "active_hosts": len(self._back),
            "seen": len(self._seen),
        }

    # -- internals ----------------------------------------------------------

    def _fill(self, now: float) -> None:
        """Admit hosts from the front queues into free back-queue slots.

        Pulls priority-first. URLs for a host that already has a back queue are
        appended to it; a URL for a new host claims a free slot (up to B).
        """
        while len(self._back) < self._back_count:
            item = self._next_front()
            if item is None:
                return
            if item.host in self._back:
                self._back[item.host].append(item)
            else:
                self._back[item.host] = deque([item])
                # te = now: a host's first contact is allowed immediately.
                heapq.heappush(self._ready, (now, self._next_seq(), item.host))

    def _next_front(self) -> FrontierItem | None:
        """Pop the highest-priority queued item (lowest front-queue index)."""
        for queue in self._front:
            if queue:
                return queue.popleft()
        return None

    def _reschedule(self, host: str, now: float) -> None:
        heapq.heappush(self._ready, (now + self._delay, self._next_seq(), host))

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq
