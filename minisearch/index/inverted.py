"""The inverted index — the data structure that makes search possible.

A forward index (doc -> terms) answers a query by scanning every document. An
inverted index (term -> docs) makes lookup proportional to the number of
documents *containing the term*, not to corpus size. That one inversion is the
whole idea; everything else here is bookkeeping to keep it fast.

Posting lists are kept **sorted by docID**. That is what turns a multi-term AND
query into a linear merge of sorted lists (Milestone 7) instead of a nested
loop, and it is why ``add_document`` requires monotonically increasing doc ids —
appending in ascending order keeps every list sorted for free, no per-query
sorting ever.

The index also maintains the corpus statistics BM25 needs: document count,
per-document token length, and average length.
"""

from __future__ import annotations

from dataclasses import dataclass

from minisearch.analyze import TermOccurrences


@dataclass(frozen=True, slots=True)
class Posting:
    """One (document, term) pairing: how often and where the term occurs."""

    doc_id: int
    tf: int
    positions: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class DocInfo:
    url: str
    title: str
    length: int          # tokens in the original stream (BM25 normalization)
    text: str            # extracted body text, kept for snippet generation


class InvertedIndex:
    """In-memory inverted index with sorted posting lists."""

    def __init__(self) -> None:
        self._postings: dict[str, list[Posting]] = {}
        self._docs: dict[int, DocInfo] = {}
        self._total_length = 0
        self._next_doc_id = 1

    # -- ingest --------------------------------------------------------------

    def add_document(
        self,
        url: str,
        title: str,
        text: str,
        terms: dict[str, TermOccurrences],
        length: int,
    ) -> int:
        """Index one document; returns its assigned doc id.

        Ids are assigned here, ascending — which is precisely what keeps every
        posting list sorted by construction.
        """
        doc_id = self._next_doc_id
        self._next_doc_id += 1

        self._docs[doc_id] = DocInfo(url=url, title=title, length=length, text=text)
        self._total_length += length
        for term, occ in terms.items():
            self._postings.setdefault(term, []).append(
                Posting(doc_id=doc_id, tf=occ.tf, positions=occ.positions)
            )
        return doc_id

    # -- lookup (the query path's entire read surface) -----------------------

    def postings(self, term: str) -> list[Posting]:
        """The posting list for ``term`` (empty if unseen), sorted by doc_id."""
        return self._postings.get(term, [])

    def doc_frequency(self, term: str) -> int:
        return len(self._postings.get(term, ()))

    def doc(self, doc_id: int) -> DocInfo:
        return self._docs[doc_id]

    @property
    def doc_count(self) -> int:
        return len(self._docs)

    @property
    def avg_doc_length(self) -> float:
        return self._total_length / len(self._docs) if self._docs else 0.0

    @property
    def term_count(self) -> int:
        return len(self._postings)

    # -- restart-from-store support (Milestone 6) ----------------------------

    def restore_document(
        self,
        doc_id: int,
        info: DocInfo,
        term_postings: dict[str, Posting],
    ) -> None:
        """Re-insert a document loaded from the store, preserving its id.

        Callers must restore in ascending doc_id order (the store's natural
        ORDER BY) so posting lists stay sorted.
        """
        self._docs[doc_id] = info
        self._total_length += info.length
        self._next_doc_id = max(self._next_doc_id, doc_id + 1)
        for term, posting in term_postings.items():
            self._postings.setdefault(term, []).append(posting)
