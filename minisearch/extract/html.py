"""HTML -> title, body text, and canonical outbound links.

Built on the stdlib ``html.parser.HTMLParser`` rather than BeautifulSoup/lxml:
the extraction we need (title, visible text, hrefs) is a single streaming pass,
and keeping the core dependency-free is a project principle. The stdlib parser
is lenient about real-world tag soup, which is what a crawler actually meets.

Every extracted link is resolved against the page URL and canonicalized with
the Milestone 1 rules, so the frontier only ever sees canonical URLs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlsplit

from minisearch.urls import canonicalize

# Content inside these elements is not page text.
_SKIP_CONTENT = frozenset({"script", "style", "noscript", "template", "svg", "head"})
# Block-level boundaries: text on either side must not run together.
_BLOCK = frozenset(
    {"p", "div", "br", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
     "tr", "td", "th", "table", "section", "article", "header", "footer",
     "blockquote", "pre", "nav", "aside", "form", "hr"}
)
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class Page:
    url: str                  # canonical URL of the page itself
    title: str
    text: str                 # visible body text, whitespace-collapsed
    links: tuple[str, ...]    # canonical, deduped, http(s)-only outlinks


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.hrefs: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_CONTENT:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.hrefs.append(value)
        if tag in _BLOCK:
            self.text_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_CONTENT and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False
        if tag in _BLOCK:
            self.text_parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        elif self._skip_depth == 0:
            self.text_parts.append(data)


def extract(url: str, html: str) -> Page:
    """Parse ``html`` fetched from ``url`` into a :class:`Page`."""
    parser = _Parser()
    parser.feed(html)
    parser.close()

    links: list[str] = []
    seen: set[str] = set()
    for href in parser.hrefs:
        href = href.strip()
        # Only crawlable schemes: skip mailto:, javascript:, tel:, data:, ...
        # A bare fragment is the same page; skip it before canonicalizing.
        if href.startswith("#"):
            continue
        canon = canonicalize(href, base=url)
        if urlsplit(canon).scheme not in ("http", "https"):
            continue
        if canon not in seen:
            seen.add(canon)
            links.append(canon)

    return Page(
        url=canonicalize(url),
        title=_WS_RE.sub(" ", "".join(parser.title_parts)).strip(),
        text=_WS_RE.sub(" ", "".join(parser.text_parts)).strip(),
        links=tuple(links),
    )
