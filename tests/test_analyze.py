"""Tests for the analyzer: Porter stemmer, tokenizer, and the full pipeline.

The stemmer vectors come from Porter's 1980 paper (and its reference
implementation's behavior) — each pins one rule, so a regression names the rule
it broke.
"""

import pytest

from minisearch.analyze import analyze, stem, tokenize

# (input, expected_stem) — grouped by the step that decides them.
PORTER_VECTORS = [
    # step 1a: plurals
    ("caresses", "caress"), ("ponies", "poni"), ("ties", "ti"),
    ("caress", "caress"), ("cats", "cat"),
    # step 1b: -eed / -ed / -ing (+ cleanup)
    ("feed", "feed"), ("agreed", "agre"), ("plastered", "plaster"),
    ("motoring", "motor"), ("sing", "sing"), ("conflated", "conflat"),
    ("troubled", "troubl"), ("sized", "size"), ("hopping", "hop"),
    ("tanned", "tan"), ("falling", "fall"), ("hissing", "hiss"),
    ("fizzed", "fizz"), ("failing", "fail"), ("filing", "file"),
    # step 1c: y -> i
    ("happy", "happi"), ("sky", "sky"),
    # step 2: derivational, m>0
    ("relational", "relat"), ("conditional", "condit"), ("rational", "ration"),
    ("valenci", "valenc"), ("digitizer", "digit"), ("radicalli", "radic"),
    ("differentli", "differ"), ("vileli", "vile"), ("analogousli", "analog"),
    ("operator", "oper"), ("feudalism", "feudal"), ("decisiveness", "decis"),
    ("hopefulness", "hope"), ("callousness", "callous"), ("formaliti", "formal"),
    ("sensitiviti", "sensit"), ("sensibiliti", "sensibl"),
    # step 3
    ("triplicate", "triplic"), ("formative", "form"), ("formalize", "formal"),
    ("electriciti", "electr"), ("electrical", "electr"), ("hopeful", "hope"),
    ("goodness", "good"),
    # step 4: m>1 strips
    ("revival", "reviv"), ("allowance", "allow"), ("inference", "infer"),
    ("airliner", "airlin"), ("gyroscopic", "gyroscop"), ("adjustable", "adjust"),
    ("defensible", "defens"), ("irritant", "irrit"), ("replacement", "replac"),
    ("adjustment", "adjust"), ("dependent", "depend"), ("adoption", "adopt"),
    ("communism", "commun"), ("activate", "activ"), ("effective", "effect"),
    ("bombardment", "bombard"),
    # step 5
    ("probate", "probat"), ("rate", "rate"), ("cease", "ceas"),
    ("controll", "control"), ("roll", "roll"),
    # multi-step compositions — the whole pipeline in one word
    ("generalizations", "gener"), ("oscillators", "oscil"),
    # guardrails
    ("a", "a"), ("is", "is"), ("be", "be"),
]


@pytest.mark.parametrize(("word", "expected"), PORTER_VECTORS)
def test_porter_vectors(word, expected):
    assert stem(word) == expected


def test_stemming_folds_inflections_together():
    # The reason stemming exists: these must all land on one index term.
    assert stem("run") == stem("runs") == stem("running")
    assert stem("connect") == stem("connected") == stem("connection") \
        == stem("connecting") == stem("connections")


# -- tokenizer ---------------------------------------------------------------


def test_tokenize_lowercases_and_splits_on_nonalnum():
    assert tokenize("Hello, World! It's 2026.") == [
        "hello", "world", "it", "s", "2026",
    ]


def test_tokenize_empty_and_punctuation_only():
    assert tokenize("") == []
    assert tokenize("!!! --- ...") == []


# -- full pipeline -----------------------------------------------------------


def test_analyze_records_tf_and_positions():
    result = analyze("running the runner runs")
    # "the" is a stopword; run/runner/runs -> "run"/"runner" stems:
    # running->run(0), runner->runner(2), runs->run(3)
    assert result["run"].positions == (0, 3)
    assert result["run"].tf == 2
    assert result["runner"].positions == (2,)


def test_analyze_drops_stopwords_but_keeps_their_positions():
    result = analyze("search the index")
    # "the" occupies position 1 even though it is not indexed — positions
    # refer to the original token stream.
    assert result["search"].positions == (0,)
    assert result["index"].positions == (2,)
    assert "the" not in result


def test_analyze_applies_stemming():
    result = analyze("connections connecting connected")
    assert set(result) == {"connect"}
    assert result["connect"].tf == 3
