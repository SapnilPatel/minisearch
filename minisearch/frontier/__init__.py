"""The URL frontier — Mercator-style two-level queue (Milestone 2).

Front queues implement priority (shallower depth = higher priority); per-host
back queues plus a min-heap of next-allowed-times implement politeness. The
split is what lets the frontier crawl important pages first AND never hammer
one host AND resist starvation by a flooding host. See frontier.py for the
full design discussion.
"""

from minisearch.frontier.frontier import Frontier, FrontierItem

__all__ = ["Frontier", "FrontierItem"]
