"""A minimal Prometheus-compatible metrics registry.

Hand-rolled rather than pulling in prometheus_client: we need three metric
types and the text exposition format, all of which fit in a page of code — and
instrumentation you wrote is instrumentation you can explain. The exposition
format follows https://prometheus.io/docs/instrumenting/exposition_formats/.

Concurrency note: everything here runs on the asyncio event loop's single
thread, so plain int/float updates need no locking. That assumption is worth
one sentence: it would NOT hold in a multi-threaded collector.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field


@dataclass
class Counter:
    """Monotonically increasing count (resets only on restart)."""

    name: str
    help: str
    value: float = 0.0

    def inc(self, amount: float = 1.0) -> None:
        self.value += amount

    def render(self) -> str:
        return (
            f"# HELP {self.name} {self.help}\n"
            f"# TYPE {self.name} counter\n"
            f"{self.name} {_fmt(self.value)}\n"
        )


@dataclass
class Gauge:
    """A value that can go up or down (queue depth, ratio, ...)."""

    name: str
    help: str
    value: float = 0.0

    def set(self, value: float) -> None:
        self.value = value

    def render(self) -> str:
        return (
            f"# HELP {self.name} {self.help}\n"
            f"# TYPE {self.name} gauge\n"
            f"{self.name} {_fmt(self.value)}\n"
        )


# Default latency buckets, in seconds: 1ms .. 10s, roughly log-spaced.
_DEFAULT_BUCKETS = (0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5,
                    1.0, 2.5, 5.0, 10.0)


@dataclass
class Histogram:
    """Cumulative-bucket histogram, Prometheus-style.

    Buckets are cumulative counts of observations <= each upper bound, plus the
    +Inf bucket == total count. Quantiles are estimated from the buckets by the
    server; we also expose _sum so rates and averages work.
    """

    name: str
    help: str
    buckets: tuple[float, ...] = _DEFAULT_BUCKETS
    counts: list[int] = field(default_factory=list)
    total: int = 0
    sum: float = 0.0

    def __post_init__(self) -> None:
        if not self.counts:
            self.counts = [0] * len(self.buckets)

    def observe(self, value: float) -> None:
        idx = bisect.bisect_left(self.buckets, value)
        if idx < len(self.counts):
            self.counts[idx] += 1
        self.total += 1
        self.sum += value

    def render(self) -> str:
        lines = [
            f"# HELP {self.name} {self.help}",
            f"# TYPE {self.name} histogram",
        ]
        cumulative = 0
        for bound, count in zip(self.buckets, self.counts, strict=True):
            cumulative += count
            lines.append(f'{self.name}_bucket{{le="{_fmt(bound)}"}} {cumulative}')
        lines.append(f'{self.name}_bucket{{le="+Inf"}} {self.total}')
        lines.append(f"{self.name}_sum {_fmt(self.sum)}")
        lines.append(f"{self.name}_count {self.total}")
        return "\n".join(lines) + "\n"


def _fmt(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(float(v))


class Registry:
    """Holds every metric and renders the /metrics payload."""

    def __init__(self) -> None:
        self._metrics: list[Counter | Gauge | Histogram] = []

    def counter(self, name: str, help: str) -> Counter:
        return self._register(Counter(name, help))

    def gauge(self, name: str, help: str) -> Gauge:
        return self._register(Gauge(name, help))

    def histogram(self, name: str, help: str, **kw) -> Histogram:
        return self._register(Histogram(name, help, **kw))

    def _register(self, metric):
        self._metrics.append(metric)
        return metric

    def render(self) -> str:
        return "".join(m.render() for m in self._metrics)
