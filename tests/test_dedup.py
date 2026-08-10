"""Tests for the bloom filter and content dedup.

The bloom filter's contract has an asymmetry worth spelling out: false positives
are a bounded, tunable cost (we skip a page we never saw), while false negatives
are IMPOSSIBLE by construction (a bit set stays set). The first test pins the
impossible half; the FPR test pins the bounded half against theory.
"""

import math

from minisearch.dedup import BloomFilter, ContentDeduper


def _urls(prefix: str, n: int) -> list[str]:
    return [f"http://{prefix}.example.com/page/{i}" for i in range(n)]


# -- the property that makes it safe: no false negatives ---------------------


def test_no_false_negatives_ever():
    bf = BloomFilter(expected_items=1000, target_fpr=0.01)
    inserted = _urls("in", 1000)
    for u in inserted:
        bf.add(u)
    # Every single inserted item must be found. Not most. All.
    assert all(u in bf for u in inserted)


def test_empty_filter_contains_nothing():
    bf = BloomFilter(expected_items=100, target_fpr=0.01)
    assert all(u not in bf for u in _urls("x", 100))
    assert len(bf) == 0


# -- sizing math -------------------------------------------------------------


def test_sizing_formulas():
    n, p = 1_000_000, 0.01
    bf = BloomFilter(expected_items=n, target_fpr=p)
    # m = -n ln p / (ln 2)^2  ->  ~9.59 bits per element at 1%
    expected_m = math.ceil(-n * math.log(p) / (math.log(2) ** 2))
    assert abs(bf.num_bits - expected_m) <= 8          # byte rounding only
    # k = (m/n) ln 2  ->  ~7 hashes at 1%
    assert bf.num_hashes == round((bf.num_bits / n) * math.log(2))
    # ~1.14 MB for a million URLs — the point of the exercise.
    assert bf.size_bytes < 1_300_000


def test_at_least_one_hash_even_for_absurd_params():
    bf = BloomFilter(expected_items=10, target_fpr=0.99)
    assert bf.num_hashes >= 1


# -- measured vs theoretical FPR ---------------------------------------------


def test_measured_fpr_close_to_theoretical():
    # Deterministic (BLAKE2b, fixed inputs): this is a real measurement, not a
    # flaky statistical test. Insert n items, probe 20k distinct non-members.
    n = 10_000
    bf = BloomFilter(expected_items=n, target_fpr=0.01)
    for u in _urls("member", n):
        bf.add(u)

    probes = _urls("nonmember", 20_000)
    false_positives = sum(1 for u in probes if u in bf)
    measured = false_positives / len(probes)

    theoretical = bf.theoretical_fpr()
    # At full load the theory predicts ~1%; measured should sit near it.
    assert theoretical < 0.011
    assert measured <= theoretical * 2      # generous upper bound, no flakes
    assert measured > 0                     # 20k probes at ~1% must hit some


def test_theoretical_fpr_grows_with_load():
    bf = BloomFilter(expected_items=100, target_fpr=0.01)
    for u in _urls("a", 50):
        bf.add(u)
    half_load = bf.theoretical_fpr()
    for u in _urls("b", 50):
        bf.add(u)
    assert bf.theoretical_fpr() > half_load


def test_stable_across_instances():
    # BLAKE2b is unsalted: two filters built the same way agree bit-for-bit.
    # (Python's builtin hash() is per-process salted and would break this —
    # and with it, any future persistence of the filter.)
    a = BloomFilter(expected_items=100, target_fpr=0.01)
    b = BloomFilter(expected_items=100, target_fpr=0.01)
    for u in _urls("x", 100):
        a.add(u)
        b.add(u)
    assert a.bits == b.bits


# -- content dedup -----------------------------------------------------------


def test_same_content_different_url_is_duplicate():
    d = ContentDeduper()
    text = "<p>identical article text</p>"
    assert d.seen_before("http://a.com/1", text) is False   # first sighting
    assert d.seen_before("http://mirror.com/1", text) is True


def test_different_content_not_duplicate():
    d = ContentDeduper()
    assert d.seen_before("http://a.com/1", "text one") is False
    assert d.seen_before("http://a.com/2", "text two") is False
    assert d.stats == {"unique": 2, "duplicates": 0}


def test_content_dedup_counts():
    d = ContentDeduper()
    d.seen_before("u1", "same")
    d.seen_before("u2", "same")
    d.seen_before("u3", "same")
    assert d.stats == {"unique": 1, "duplicates": 2}
