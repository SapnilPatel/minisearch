"""Tests for the hand-rolled Prometheus registry."""

from minisearch.metrics import Registry


def test_counter_renders_prometheus_format():
    reg = Registry()
    c = reg.counter("app_things_total", "Things counted")
    c.inc()
    c.inc(2)
    out = reg.render()
    assert "# TYPE app_things_total counter" in out
    assert "app_things_total 3" in out


def test_gauge_goes_up_and_down():
    reg = Registry()
    g = reg.gauge("app_depth", "Queue depth")
    g.set(10)
    g.set(4.5)
    assert "app_depth 4.5" in reg.render()


def test_histogram_buckets_are_cumulative():
    reg = Registry()
    h = reg.histogram("app_latency_seconds", "Latency", buckets=(0.1, 1.0, 10.0))
    for v in (0.05, 0.05, 0.5, 5.0):
        h.observe(v)
    out = reg.render()
    assert 'app_latency_seconds_bucket{le="0.1"} 2' in out
    assert 'app_latency_seconds_bucket{le="1"} 3' in out          # cumulative
    assert 'app_latency_seconds_bucket{le="10"} 4' in out
    assert 'app_latency_seconds_bucket{le="+Inf"} 4' in out
    assert "app_latency_seconds_count 4" in out
    assert "app_latency_seconds_sum 5.6" in out


def test_histogram_observation_beyond_last_bucket():
    reg = Registry()
    h = reg.histogram("h", "H", buckets=(1.0,))
    h.observe(100.0)                      # lands only in +Inf
    out = reg.render()
    assert 'h_bucket{le="1"} 0' in out
    assert 'h_bucket{le="+Inf"} 1' in out


def test_multiple_metrics_render_together():
    reg = Registry()
    reg.counter("a_total", "A")
    reg.gauge("b", "B")
    out = reg.render()
    assert "# TYPE a_total counter" in out and "# TYPE b gauge" in out
