"""The Porter stemming algorithm, hand-rolled from the original paper.

M.F. Porter, "An algorithm for suffix stripping", Program 14(3), 1980.

Why stem at all: recall — a query for "run" should match documents saying
"running" and "runs". What it costs: precision — the stemmer is intentionally
dumb about meaning, so "university" and "universe" can collapse to the same
stem. That trade-off is the whole conversation about stemming.

The algorithm is five steps of suffix rewrites. Each rule fires only if the
remaining stem satisfies a *measure* condition. Definitions from the paper:

* A word is viewed as ``[C](VC)^m[V]`` where C/V are maximal consonant/vowel
  runs; ``m`` is the **measure**. Roughly: m counts vowel→consonant transitions,
  a proxy for syllables. ``tr|ee`` has m=0, ``trou|bl|e`` m=1, ``priv|at|e`` m=2.
* ``y`` is a vowel when preceded by a consonant ("happy" -> the y is a vowel),
  a consonant otherwise ("yellow").

Within a step, the longest matching suffix decides which single rule applies —
even if its condition then fails, no other rule in that step is tried. Getting
that detail wrong is the classic Porter implementation bug.
"""

from __future__ import annotations


def _is_consonant(word: str, i: int) -> bool:
    ch = word[i]
    if ch in "aeiou":
        return False
    if ch == "y":
        # y after a consonant acts as a vowel; leading y is a consonant.
        return i == 0 or not _is_consonant(word, i - 1)
    return True


def _measure(stem: str) -> int:
    """The number of VC sequences in ``stem`` — Porter's m."""
    m = 0
    prev_vowel = False
    for i in range(len(stem)):
        if _is_consonant(stem, i):
            if prev_vowel:
                m += 1
            prev_vowel = False
        else:
            prev_vowel = True
    return m


def _contains_vowel(stem: str) -> bool:
    return any(not _is_consonant(stem, i) for i in range(len(stem)))


def _ends_double_consonant(word: str) -> bool:
    return (
        len(word) >= 2
        and word[-1] == word[-2]
        and _is_consonant(word, len(word) - 1)
    )


def _ends_cvc(word: str) -> bool:
    """*o: stem ends consonant-vowel-consonant, final consonant not w, x, y.

    The condition that distinguishes "hop(p)ing"->"hop"+e? no — it restores the
    silent e on words like "fil" -> "file" after -ing removal.
    """
    if len(word) < 3:
        return False
    return (
        _is_consonant(word, len(word) - 3)
        and not _is_consonant(word, len(word) - 2)
        and _is_consonant(word, len(word) - 1)
        and word[-1] not in "wxy"
    )


def stem(word: str) -> str:
    """Return the Porter stem of ``word`` (assumed lowercase)."""
    if len(word) <= 2:
        return word  # 1- and 2-letter words are never stemmed

    word = _step1a(word)
    word = _step1b(word)
    word = _step1c(word)
    word = _step2(word)
    word = _step3(word)
    word = _step4(word)
    word = _step5a(word)
    word = _step5b(word)
    return word


# -- step 1: plurals and -ed / -ing ------------------------------------------


def _step1a(w: str) -> str:
    if w.endswith("sses"):
        return w[:-2]           # caresses -> caress
    if w.endswith("ies"):
        return w[:-2]           # ponies -> poni, ties -> ti
    if w.endswith("ss"):
        return w                # caress -> caress
    if w.endswith("s"):
        return w[:-1]           # cats -> cat
    return w


def _step1b(w: str) -> str:
    if w.endswith("eed"):
        # (m>0) EED -> EE : agreed -> agree, but feed -> feed
        if _measure(w[:-3]) > 0:
            return w[:-1]
        return w
    fired = False
    if w.endswith("ed") and _contains_vowel(w[:-2]):
        w, fired = w[:-2], True         # plastered -> plaster
    elif w.endswith("ing") and _contains_vowel(w[:-3]):
        w, fired = w[:-3], True         # motoring -> motor
    if fired:
        # Cleanup pass: the removal may have exposed a mangled stem.
        if w.endswith(("at", "bl", "iz")):
            return w + "e"              # conflat -> conflate
        if _ends_double_consonant(w) and w[-1] not in "lsz":
            return w[:-1]               # hopp -> hop, but fall -> fall
        if _measure(w) == 1 and _ends_cvc(w):
            return w + "e"              # fil -> file
    return w


def _step1c(w: str) -> str:
    if w.endswith("y") and _contains_vowel(w[:-1]):
        return w[:-1] + "i"             # happy -> happi (sky -> sky: no vowel)
    return w


# -- steps 2-4: derivational suffixes, longest match first -------------------

# (suffix, replacement) pairs; within a step the longest matching suffix wins
# and its rule alone applies. Order within equal lengths doesn't matter because
# suffix matches are mutually exclusive at a given length.

_STEP2 = [
    ("ational", "ate"), ("tional", "tion"), ("enci", "ence"), ("anci", "ance"),
    ("izer", "ize"), ("abli", "able"), ("alli", "al"), ("entli", "ent"),
    ("eli", "e"), ("ousli", "ous"), ("ization", "ize"), ("ation", "ate"),
    ("ator", "ate"), ("alism", "al"), ("iveness", "ive"), ("fulness", "ful"),
    ("ousness", "ous"), ("aliti", "al"), ("iviti", "ive"), ("biliti", "ble"),
]

_STEP3 = [
    ("icate", "ic"), ("ative", ""), ("alize", "al"), ("iciti", "ic"),
    ("ical", "ic"), ("ful", ""), ("ness", ""),
]

_STEP4 = [
    "al", "ance", "ence", "er", "ic", "able", "ible", "ant", "ement", "ment",
    "ent", "ion", "ou", "ism", "ate", "iti", "ous", "ive", "ize",
]


def _longest_match(w: str, rules: list[tuple[str, str]]) -> tuple[str, str] | None:
    best = None
    for suffix, repl in rules:
        if w.endswith(suffix) and (best is None or len(suffix) > len(best[0])):
            best = (suffix, repl)
    return best


def _step2(w: str) -> str:
    match = _longest_match(w, _STEP2)
    if match:
        suffix, repl = match
        if _measure(w[: -len(suffix)]) > 0:
            return w[: -len(suffix)] + repl
    return w


def _step3(w: str) -> str:
    match = _longest_match(w, _STEP3)
    if match:
        suffix, repl = match
        if _measure(w[: -len(suffix)]) > 0:
            return w[: -len(suffix)] + repl
    return w


def _step4(w: str) -> str:
    best = None
    for suffix in _STEP4:
        if w.endswith(suffix) and (best is None or len(suffix) > len(best)):
            best = suffix
    if best is None:
        return w
    stem_part = w[: -len(best)]
    if _measure(stem_part) > 1:
        # ION only strips after s or t (adoption -> adopt, not "ion" generally).
        if best == "ion" and not stem_part.endswith(("s", "t")):
            return w
        return stem_part
    return w


# -- step 5: final e and double l --------------------------------------------


def _step5a(w: str) -> str:
    if w.endswith("e"):
        m = _measure(w[:-1])
        if m > 1:
            return w[:-1]               # probate -> probat
        if m == 1 and not _ends_cvc(w[:-1]):
            return w[:-1]               # cease -> ceas, but rate -> rate
    return w


def _step5b(w: str) -> str:
    if _measure(w) > 1 and _ends_double_consonant(w) and w.endswith("l"):
        return w[:-1]                   # controll -> control, roll -> roll
    return w
