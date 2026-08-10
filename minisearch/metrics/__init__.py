"""Observability — Prometheus instrumentation (Milestone 8).

Exposes pages fetched/sec, frontier depth, fetch error rate by class, index write
throughput, a query-latency histogram, and the measured bloom-filter FPR.
"""

from minisearch.metrics.registry import Counter, Gauge, Histogram, Registry

__all__ = ["Counter", "Gauge", "Histogram", "Registry"]
