"""Tests for URL canonicalization.

Each test names the normalization rule it exercises. Together they pin down the
policy decisions so a future change that quietly alters folding behavior fails
loudly here.
"""

import pytest

from minisearch.urls import canonicalize


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # scheme + host are case-insensitive; the PATH is not (stays as-is).
        ("HTTP://EXAMPLE.COM/A", "http://example.com/A"),
        ("http://Example.Com/a", "http://example.com/a"),
        # default ports are redundant; non-default ports are kept.
        ("http://example.com:80/a", "http://example.com/a"),
        ("https://example.com:443/a", "https://example.com/a"),
        ("http://example.com:8080/a", "http://example.com:8080/a"),
        # fragments never reach the server -> dropped.
        ("http://example.com/a#section", "http://example.com/a"),
        ("http://example.com/a#", "http://example.com/a"),
        # dot-segments resolved.
        ("http://example.com/a/../b", "http://example.com/b"),
        ("http://example.com/a/./b", "http://example.com/a/b"),
        ("http://example.com/a/b/../../c", "http://example.com/c"),
        # trailing slash stripped, except at the root; empty path -> '/'.
        ("http://example.com/a/", "http://example.com/a"),
        ("http://example.com/", "http://example.com/"),
        ("http://example.com", "http://example.com/"),
        ("http://example.com/a/b/", "http://example.com/a/b"),
        # host trailing dot removed.
        ("http://example.com./a", "http://example.com/a"),
    ],
)
def test_basic_rules(raw, expected):
    assert canonicalize(raw) == expected


def test_query_params_sorted():
    assert canonicalize("http://example.com/?b=2&a=1") == "http://example.com/?a=1&b=2"
    # reordering the same params yields the same canonical URL.
    assert canonicalize("http://x.com/?c=3&a=1&b=2") == canonicalize(
        "http://x.com/?a=1&b=2&c=3"
    )


def test_tracking_params_dropped():
    assert (
        canonicalize("http://example.com/p?utm_source=news&q=go&fbclid=xyz")
        == "http://example.com/p?q=go"
    )
    # a URL that is ONLY tracking params loses its query entirely (no '?').
    assert canonicalize("http://example.com/p?utm_medium=email") == "http://example.com/p"


def test_percent_encoding_normalized():
    # %7E is an unreserved char (~) -> decoded.
    assert canonicalize("http://example.com/%7Euser") == "http://example.com/~user"
    # lowercase hex in a reserved-char escape is uppercased, not decoded.
    assert canonicalize("http://example.com/a%2fb") == "http://example.com/a%2Fb"


def test_relative_resolution_against_base():
    assert (
        canonicalize("../b", base="http://example.com/x/y") == "http://example.com/b"
    )
    assert (
        canonicalize("/other", base="http://example.com/x/y")
        == "http://example.com/other"
    )
    assert (
        canonicalize("page.html", base="http://example.com/dir/")
        == "http://example.com/dir/page.html"
    )


def test_www_and_scheme_are_not_unified():
    # www is significant: not stripped.
    assert canonicalize("http://www.example.com/a") == "http://www.example.com/a"
    assert canonicalize("http://www.example.com/a") != canonicalize(
        "http://example.com/a"
    )
    # http and https are distinct resources.
    assert canonicalize("http://example.com/a") != canonicalize("https://example.com/a")


@pytest.mark.parametrize(
    "raw",
    [
        "http://example.com/a/../b?utm_source=x&z=1&a=2#frag",
        "HTTPS://Example.COM:443/x/./y/",
        "http://example.com",
        "http://example.com/%7Euser/",
    ],
)
def test_idempotent(raw):
    once = canonicalize(raw)
    assert canonicalize(once) == once
