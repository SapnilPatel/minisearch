"""Tests for the query engine: parsing, intersection, semantics, ranking order,
phrases, and snippets — the "walk me through a query end to end" milestone."""

from minisearch.analyze import analyze
from minisearch.index import InvertedIndex, Posting
from minisearch.query import QueryEngine, intersect, parse_query


def _engine(*docs: tuple[str, str]) -> QueryEngine:
    idx = InvertedIndex()
    for title, text in docs:
        terms = analyze(text)
        idx.add_document(
            url=f"http://d/{title}", title=title, text=text, terms=terms,
            length=sum(o.tf for o in terms.values()),
        )
    return QueryEngine(idx)


CORPUS = [
    ("linux", "the epoll interface scales better than select on linux servers"),
    ("bsd", "kqueue is the bsd equivalent of the linux epoll interface"),
    ("web", "web servers handle many connections using event driven interfaces"),
    ("cooking", "a slow cooker recipe for pulled pork with spices"),
]


# -- parsing -----------------------------------------------------------------


def test_parse_terms_are_analyzed():
    groups, is_and = parse_query("Running Servers")
    assert is_and
    assert [g.terms for g in groups] == [("run",), ("server",)]


def test_parse_quoted_phrase_and_or():
    groups, is_and = parse_query('"machine learning" OR robotics')
    assert not is_and
    assert groups[0].is_phrase and groups[0].terms == ("machin", "learn")
    assert groups[0].offsets == (0, 1)
    assert groups[1].terms == ("robot",)


def test_parse_stopwords_dropped_from_query():
    groups, _ = parse_query("the epoll of")
    assert [g.terms for g in groups] == [("epol",)]


# -- intersection ------------------------------------------------------------


def _plist(*doc_ids: int) -> list[Posting]:
    return [Posting(doc_id=d, tf=1, positions=(0,)) for d in doc_ids]


def test_intersect_sorted_lists():
    assert [p.doc_id for p in intersect(_plist(1, 3, 5, 7), _plist(2, 3, 7, 9))] == [3, 7]
    assert intersect(_plist(1, 2), _plist(3, 4)) == []
    assert intersect(_plist(), _plist(1)) == []


# -- semantics ---------------------------------------------------------------


def test_and_requires_all_terms():
    eng = _engine(*CORPUS)
    urls = {h.url for h in eng.search("epoll linux")}
    assert urls == {"http://d/linux", "http://d/bsd"}   # both mention both


def test_or_unions():
    eng = _engine(*CORPUS)
    urls = {h.url for h in eng.search("kqueue OR cooker")}
    assert urls == {"http://d/bsd", "http://d/cooking"}


def test_unknown_term_and_empty_query():
    eng = _engine(*CORPUS)
    assert eng.search("xyzzy") == []
    assert eng.search("epoll xyzzy") == []              # AND with a miss is empty
    assert eng.search("") == []
    assert eng.search('"  "') == []


def test_limit_respected():
    eng = _engine(*[(f"d{i}", "shared term here") for i in range(20)])
    assert len(eng.search("shared", limit=5)) == 5


# -- ranking order -----------------------------------------------------------


def test_rare_term_match_outranks_common_term_match():
    eng = _engine(
        ("target", "epoll epoll tuning notes"),
        ("noise1", "server notes and more notes"),
        ("noise2", "server deployment notes"),
        ("both", "server epoll notes"),
    )
    hits = eng.search("epoll OR server")
    # Docs containing the rarer "epoll" outrank the server-only doc.
    assert hits[0].url in ("http://d/target", "http://d/both")
    assert hits[-1].url == "http://d/noise1" or hits[-1].url == "http://d/noise2"


def test_higher_tf_ranks_higher_all_else_equal():
    eng = _engine(
        ("twice", "cache cache design"),
        ("once", "cache miss design"),
    )
    hits = eng.search("cache")
    assert hits[0].url == "http://d/twice"


def test_stemming_bridges_query_and_document():
    eng = _engine(("doc", "running the servers"))
    assert eng.search("runs server")                    # inflections still match


# -- phrases -----------------------------------------------------------------


def test_phrase_requires_adjacency():
    eng = _engine(
        ("exact", "machine learning is transforming search"),
        ("scrambled", "learning about the machine took a while"),
    )
    urls = {h.url for h in eng.search('"machine learning"')}
    assert urls == {"http://d/exact"}


def test_phrase_and_term_combined():
    eng = _engine(
        ("match", "machine learning for search ranking"),
        ("phrase_only", "machine learning for vision"),
    )
    urls = {h.url for h in eng.search('"machine learning" search')}
    assert urls == {"http://d/match"}


def test_three_word_phrase():
    eng = _engine(
        ("exact", "big red dog runs fast"),
        ("gapped", "big dog with red collar"),
    )
    urls = {h.url for h in eng.search('"big red dog"')}
    assert urls == {"http://d/exact"}


# -- snippets ----------------------------------------------------------------


def test_snippet_windows_around_match():
    filler = "irrelevant words " * 30
    eng = _engine(("doc", filler + "the epoll interface appears here " + filler))
    hits = eng.search("epoll")
    assert "epoll" in hits[0].snippet
    assert hits[0].snippet.startswith("…")              # window, not the whole doc
    assert len(hits[0].snippet.split()) < 40


def test_snippet_short_doc_no_ellipsis():
    eng = _engine(("doc", "tiny epoll doc"))
    assert eng.search("epoll")[0].snippet == "tiny epoll doc"
