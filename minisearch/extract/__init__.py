"""HTML -> text and links (Milestone 5).

Parses HTML into title, body text, and outbound links, normalizing each link to
a canonical absolute URL via the urls package.
"""

from minisearch.extract.html import Page, extract

__all__ = ["Page", "extract"]
