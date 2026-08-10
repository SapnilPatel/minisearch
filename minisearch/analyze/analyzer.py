"""Text analysis: tokenize -> lowercase -> drop stopwords -> stem -> positions.

The output is what the inverted index stores: for each surviving term, its
frequency and the positions where it occurred. Positions are indices in the
*original* token stream (stopwords still count a slot even though they are not
indexed). That choice keeps positions stable and cheap, with a documented
limitation: a phrase query whose words were separated by a stopword ("state of
the art") cannot match as an exact phrase, because the gap survives. The
alternative — renumbering after stopword removal — would make unrelated words
look adjacent, which is worse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from minisearch.analyze.porter import stem

# Standard English stopwords: words so common their postings would cover most of
# the corpus (huge lists, no discriminating power). Dropping them shrinks the
# index and speeds queries; the cost is exact-phrase matching across them.
STOPWORDS = frozenset(
    """
    a about above after again all am an and any are as at be because been before
    being below between both but by can could did do does doing down during each
    few for from further had has have having he her here hers him his how i if
    in into is it its itself just me more most my no nor not now of off on once
    only or other our ours out over own same she should so some such than that
    the their theirs them then there these they this those through to too under
    until up very was we were what when where which while who whom why will with
    would you your yours
    """.split()
)

# A token is a run of letters/digits; everything else separates. \w includes _,
# so spell it explicitly.
_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class TermOccurrences:
    term: str
    positions: tuple[int, ...]   # ascending original-token-stream indices

    @property
    def tf(self) -> int:
        return len(self.positions)


def tokenize(text: str) -> list[str]:
    """Lowercase and split into raw tokens (stopwords still included)."""
    return _TOKEN_RE.findall(text.lower())


def analyze(text: str) -> dict[str, TermOccurrences]:
    """Full pipeline: the term -> occurrences map the index ingests."""
    positions: dict[str, list[int]] = {}
    for pos, token in enumerate(tokenize(text)):
        if token in STOPWORDS:
            continue
        term = stem(token)
        positions.setdefault(term, []).append(pos)
    return {
        term: TermOccurrences(term=term, positions=tuple(pos_list))
        for term, pos_list in positions.items()
    }
