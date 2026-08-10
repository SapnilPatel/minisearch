"""Tests for the in-memory inverted index."""

from minisearch.analyze import analyze
from minisearch.index import DocInfo, InvertedIndex, Posting


def _add(index: InvertedIndex, url: str, text: str) -> int:
    terms = analyze(text)
    length = sum(occ.tf for occ in terms.values())
    return index.add_document(url=url, title="t", text=text, terms=terms, length=length)


def test_postings_record_tf_and_positions():
    idx = InvertedIndex()
    doc = _add(idx, "http://a.com/1", "search engines search the web")
    postings = idx.postings("search")
    assert len(postings) == 1
    assert postings[0].doc_id == doc
    assert postings[0].tf == 2
    assert postings[0].positions == (0, 2)


def test_posting_lists_sorted_by_doc_id():
    idx = InvertedIndex()
    ids = [_add(idx, f"http://a.com/{i}", "common term here") for i in range(20)]
    postings = idx.postings("common")
    assert [p.doc_id for p in postings] == sorted(ids)


def test_doc_frequency_and_corpus_stats():
    idx = InvertedIndex()
    _add(idx, "u1", "apple banana")
    _add(idx, "u2", "apple cherry cherry")
    assert idx.doc_frequency("appl") == 2        # stemmed term
    assert idx.doc_frequency("banana") == 1
    assert idx.doc_frequency("missing") == 0
    assert idx.doc_count == 2
    assert idx.avg_doc_length == (2 + 3) / 2


def test_unknown_term_returns_empty_list():
    idx = InvertedIndex()
    assert idx.postings("nothing") == []


def test_restore_preserves_ids_and_sort_order():
    idx = InvertedIndex()
    idx.restore_document(
        5, DocInfo(url="u5", title="", length=3, text="x"),
        {"term": Posting(doc_id=5, tf=1, positions=(0,))},
    )
    idx.restore_document(
        9, DocInfo(url="u9", title="", length=2, text="y"),
        {"term": Posting(doc_id=9, tf=2, positions=(0, 1))},
    )
    assert [p.doc_id for p in idx.postings("term")] == [5, 9]
    assert idx.doc_count == 2
    # New documents after a restore continue from the highest restored id.
    new_id = _add(idx, "http://new.com", "fresh")
    assert new_id == 10
