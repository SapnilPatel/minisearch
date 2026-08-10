"""Tests for BM25 and top-K selection.

The BM25 tests pin behaviors, not magic numbers: what k1 and b *do* at their
extremes is exactly what an interviewer asks, so each property gets a test that
demonstrates it.
"""

from minisearch.analyze import analyze
from minisearch.index import InvertedIndex
from minisearch.rank import BM25, TopK


def _index(*texts: str) -> InvertedIndex:
    idx = InvertedIndex()
    for i, text in enumerate(texts):
        terms = analyze(text)
        idx.add_document(
            url=f"http://d/{i}", title="", text=text, terms=terms,
            length=sum(o.tf for o in terms.values()),
        )
    return idx


# -- IDF ---------------------------------------------------------------------


def test_rare_terms_weigh_more_than_common():
    idx = _index("zebra common", "common", "common", "common")
    ranker = BM25(idx)
    assert ranker.idf("zebra") > ranker.idf("common")


def test_idf_never_negative():
    # "common" is in every document — Robertson IDF would go negative here;
    # the +1 variant must not.
    idx = _index("common a", "common b", "common c")
    assert BM25(idx).idf("common") > 0


# -- k1: term-frequency saturation -------------------------------------------


def test_tf_gains_saturate():
    idx = _index("word " * 50, "other doc")
    ranker = BM25(idx)
    gain_low = ranker.score("word", 2, 10) - ranker.score("word", 1, 10)
    gain_high = ranker.score("word", 20, 10) - ranker.score("word", 19, 10)
    assert gain_low > gain_high > 0        # 2nd occurrence worth more than 20th


def test_k1_zero_means_binary_match():
    idx = _index("word doc one", "other doc")
    ranker = BM25(idx, k1=0.0)
    # With k1=0 the tf fraction is identically 1: tf stops mattering.
    assert ranker.score("word", 1, 10) == ranker.score("word", 100, 10)


# -- b: length normalization -------------------------------------------------


def test_same_tf_shorter_doc_scores_higher():
    idx = _index("apple " + "filler " * 40, "apple pie")
    ranker = BM25(idx)
    assert ranker.score("appl", 1, 2) > ranker.score("appl", 1, 41)


def test_b_zero_ignores_length():
    idx = _index("apple " + "x " * 100, "apple")
    ranker = BM25(idx, b=0.0)
    assert ranker.score("appl", 1, 2) == ranker.score("appl", 1, 101)


# -- TopK --------------------------------------------------------------------


def test_topk_matches_full_sort():
    scores = [(i * 37 % 101) / 7.0 for i in range(500)]
    topk = TopK(10)
    for i, s in enumerate(scores):
        topk.offer(s, f"item{i}")
    expected = sorted(scores, reverse=True)[:10]
    assert [s for s, _ in topk.results()] == expected


def test_topk_fewer_items_than_k():
    topk = TopK(10)
    topk.offer(1.0, "a")
    topk.offer(3.0, "b")
    assert [(s, i) for s, i in topk.results()] == [(3.0, "b"), (1.0, "a")]


def test_topk_ties_keep_insertion_order():
    topk = TopK(2)
    topk.offer(1.0, "first")
    topk.offer(1.0, "second")
    topk.offer(1.0, "third")               # tie with the worst: not admitted
    assert [i for _, i in topk.results()] == ["first", "second"]


def test_topk_memory_stays_bounded():
    topk = TopK(5)
    for i in range(100_000):
        topk.offer(float(i % 1000), i)
    assert len(topk._heap) == 5            # never more than K entries held
