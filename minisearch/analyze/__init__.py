"""Text -> terms (Milestone 5).

Tokenizes on non-alphanumerics, lowercases, drops stopwords, applies Porter
stemming, and records term frequency and positions. Positions cost space but
enable phrase queries.
"""

from minisearch.analyze.analyzer import STOPWORDS, TermOccurrences, analyze, tokenize
from minisearch.analyze.porter import stem

__all__ = ["STOPWORDS", "TermOccurrences", "analyze", "stem", "tokenize"]
