"""Tests for the Mercator-style URL frontier.

Time is passed explicitly (a fake clock), so politeness is verified without a
single sleep. Each test names the property it pins down.
"""

from minisearch.config import Config
from minisearch.frontier import Frontier


def make(delay=1.0, max_size=100_000, back_queues=None, front_queues=10):
    cfg = Config(per_host_delay_s=delay, max_frontier_size=max_size)
    return Frontier(cfg, front_queues=front_queues, back_queues=back_queues or 8)


# -- priority ----------------------------------------------------------------


def test_shallower_depth_pops_first():
    f = make()
    f.add("http://a.com/deep", depth=3)
    f.add("http://b.com/shallow", depth=0)
    item = f.pop_ready(now=0.0)
    assert item is not None and item.url == "http://b.com/shallow"


def test_fifo_within_same_depth_and_host():
    f = make(delay=0.0)
    f.add("http://a.com/1", depth=1)
    f.add("http://a.com/2", depth=1)
    assert f.pop_ready(0.0).url == "http://a.com/1"
    assert f.pop_ready(0.0).url == "http://a.com/2"


def test_depth_beyond_last_bucket_clamps():
    f = make(front_queues=3)
    assert f.add("http://a.com/x", depth=99) is True     # clamps, doesn't crash
    assert f.pop_ready(0.0) is not None


# -- politeness --------------------------------------------------------------


def test_same_host_respects_delay():
    f = make(delay=2.0)
    f.add("http://a.com/1")
    f.add("http://a.com/2")
    assert f.pop_ready(now=0.0) is not None
    assert f.pop_ready(now=0.5) is None          # still inside the delay window
    assert f.time_until_ready(now=0.5) == 1.5
    assert f.pop_ready(now=2.0) is not None      # window elapsed


def test_different_hosts_are_independent():
    f = make(delay=5.0)
    f.add("http://a.com/1")
    f.add("http://b.com/1")
    first = f.pop_ready(now=0.0)
    second = f.pop_ready(now=0.0)                # different host: no wait
    assert first is not None and second is not None
    assert first.host != second.host


# -- fairness: the "one host dominates" question -----------------------------


def test_flooding_host_cannot_starve_others():
    f = make(delay=1.0)
    # Host a.com floods 50 URLs at depth 0; b.com has one deeper URL.
    for i in range(50):
        f.add(f"http://a.com/{i}", depth=0)
    f.add("http://b.com/only", depth=5)

    popped = [f.pop_ready(now=0.0), f.pop_ready(now=0.0)]
    hosts = {item.host for item in popped if item is not None}
    # While a.com sits out its politeness delay, b.com is served — the flood
    # cannot monopolize the fetcher.
    assert hosts == {"a.com", "b.com"}


def test_interleaves_hosts_over_time():
    f = make(delay=1.0)
    for i in range(3):
        f.add(f"http://a.com/{i}")
        f.add(f"http://b.com/{i}")
    order = []
    now = 0.0
    while (item := f.pop_ready(now)) is not None or len(f) > 0:
        if item is None:
            now += f.time_until_ready(now)
            continue
        order.append(item.host)
    # Never two consecutive fetches of the same host without its delay: with two
    # hosts and equal work, the sequence strictly alternates.
    assert order[:2] in (["a.com", "b.com"], ["b.com", "a.com"])
    for prev, cur in zip(order, order[1:], strict=False):
        assert prev != cur


# -- dedup and bounds --------------------------------------------------------


def test_duplicate_urls_rejected_via_canonicalization():
    f = make()
    assert f.add("http://a.com/page") is True
    # Same page, different spelling — canonicalization catches it.
    assert f.add("HTTP://A.COM/page#frag") is False
    assert f.stats["enqueued"] == 1


def test_bounded_size_rejects_and_counts_drops():
    f = make(max_size=2)
    assert f.add("http://a.com/1") is True
    assert f.add("http://a.com/2") is True
    assert f.add("http://a.com/3") is False
    assert f.stats["dropped"] == 1
    assert len(f) == 2


def test_popped_urls_are_never_readded():
    f = make(delay=0.0)
    f.add("http://a.com/1")
    assert f.pop_ready(0.0) is not None
    assert f.add("http://a.com/1") is False      # seen forever, not just while queued


# -- empty / exhaustion ------------------------------------------------------


def test_empty_frontier():
    f = make()
    assert f.pop_ready(0.0) is None
    assert f.time_until_ready(0.0) is None
    assert len(f) == 0


def test_drains_completely():
    f = make(delay=0.0)
    for i in range(20):
        f.add(f"http://h{i % 4}.com/{i}")
    count = 0
    while f.pop_ready(0.0) is not None:
        count += 1
    assert count == 20
    assert len(f) == 0


def test_more_hosts_than_back_queues():
    # 6 hosts but only 2 back-queue slots: everything still gets served.
    f = make(delay=0.0, back_queues=2)
    for i in range(6):
        f.add(f"http://h{i}.com/x")
    served = set()
    while (item := f.pop_ready(0.0)) is not None:
        served.add(item.host)
    assert len(served) == 6
