"""The inverted index — the core data structure (Milestone 6).

Maps each term to a posting list: the documents containing it, each with term
frequency and positions. Posting lists are kept sorted by docID so multi-term
AND queries are a linear merge of sorted lists, not a nested loop.
"""

from minisearch.index.inverted import DocInfo, InvertedIndex, Posting

__all__ = ["DocInfo", "InvertedIndex", "Posting"]
