"""Tests for the HTML extractor."""

from minisearch.extract import extract

BASE = "http://example.com/dir/page.html"


def test_title_text_and_links():
    html = """
    <html><head><title>  My   Page </title>
    <style>body { color: red }</style></head>
    <body>
      <h1>Heading</h1>
      <p>Some <b>bold</b> text.</p>
      <a href="/absolute">abs</a>
      <a href="relative.html">rel</a>
      <a href="http://other.com/x?b=2&a=1">other</a>
      <script>var ignored = "script text";</script>
    </body></html>
    """
    page = extract(BASE, html)
    assert page.title == "My Page"
    assert "Heading" in page.text and "bold" in page.text
    assert "script text" not in page.text
    assert "color: red" not in page.text
    assert page.links == (
        "http://example.com/absolute",
        "http://example.com/dir/relative.html",
        "http://other.com/x?a=1&b=2",          # canonicalized: params sorted
    )


def test_uncrawlable_schemes_and_fragments_skipped():
    html = """
    <a href="mailto:x@example.com">mail</a>
    <a href="javascript:void(0)">js</a>
    <a href="tel:+15551234567">tel</a>
    <a href="#section">frag</a>
    <a href="/ok">ok</a>
    """
    page = extract(BASE, html)
    assert page.links == ("http://example.com/ok",)


def test_links_deduped_after_canonicalization():
    html = """
    <a href="/a">1</a>
    <a href="/a#top">2</a>
    <a href="/a/">3</a>
    """
    page = extract(BASE, html)
    assert page.links == ("http://example.com/a",)


def test_block_elements_separate_words():
    # </td><td> and </li><li> must not glue adjacent words together.
    html = (
        "<table><tr><td>alpha</td><td>beta</td></tr></table>"
        "<ul><li>gamma</li><li>delta</li></ul>"
    )
    page = extract(BASE, html)
    assert "alpha beta" in page.text
    assert "gamma delta" in page.text
    assert "alphabeta" not in page.text


def test_tag_soup_does_not_crash():
    page = extract(BASE, "<p>unclosed <b>nested <i>mess <a href='/x'>link")
    assert "unclosed" in page.text
    assert page.links == ("http://example.com/x",)


def test_entities_decoded():
    page = extract(BASE, "<p>fish &amp; chips &lt;3</p>")
    assert "fish & chips <3" in page.text
