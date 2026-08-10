"""BM25 ranking.

Why not raw term counts: they favor long documents (more words, more matches)
and weight "the" as heavily as "epoll". Why not classic TF-IDF: term frequency
enters linearly, so the 20th occurrence counts as much as the 2nd. BM25 fixes
both with two ideas:

    score(D,Q) = sum over query terms q of
        IDF(q) * tf(q,D) * (k1 + 1)
                 -----------------------------------------
                 tf(q,D) + k1 * (1 - b + b * |D| / avgdl)

* **Saturation** (k1): as tf grows the fraction approaches (k1+1) — each extra
  occurrence is worth less. k1=0 ignores tf entirely (binary match); large k1
  approaches linear tf.
* **Length normalization** (b): the |D|/avgdl factor discounts matches in long
  documents. b=0 turns it off; b=1 normalizes fully. b=0.75 is the literature's
  default compromise.

IDF uses the "+1 inside the log" variant, IDF = ln(1 + (N - df + 0.5)/(df + 0.5)),
which stays positive even when a term appears in more than half the corpus —
the raw Robertson form goes negative there, and a negative-scoring query term
is never what you want in an AND query.
"""

from __future__ import annotations

import math

from minisearch.index import InvertedIndex

DEFAULT_K1 = 1.5
DEFAULT_B = 0.75


class BM25:
    def __init__(
        self,
        index: InvertedIndex,
        k1: float = DEFAULT_K1,
        b: float = DEFAULT_B,
    ) -> None:
        self._index = index
        self._k1 = k1
        self._b = b

    def idf(self, term: str) -> float:
        n = self._index.doc_count
        df = self._index.doc_frequency(term)
        return math.log(1.0 + (n - df + 0.5) / (df + 0.5))

    def score(self, term: str, tf: int, doc_length: int) -> float:
        """Score one term's contribution for one document."""
        avgdl = self._index.avg_doc_length or 1.0
        k1, b = self._k1, self._b
        norm = k1 * (1.0 - b + b * doc_length / avgdl)
        return self.idf(term) * (tf * (k1 + 1.0)) / (tf + norm)
