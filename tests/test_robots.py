"""Tests for robots.txt parsing and rule matching."""

from minisearch.robots import parse_robots

UA = "minisearch-bot"


def test_default_allow_when_no_rules():
    rules = parse_robots("", UA)
    assert rules.can_fetch("/anything") is True


def test_simple_disallow():
    txt = "User-agent: *\nDisallow: /private\n"
    rules = parse_robots(txt, UA)
    assert rules.can_fetch("/private/x") is False
    assert rules.can_fetch("/public") is True


def test_empty_disallow_means_allow_all():
    txt = "User-agent: *\nDisallow:\n"
    rules = parse_robots(txt, UA)
    assert rules.can_fetch("/anything") is True


def test_longest_match_wins_and_allow_breaks_ties():
    # /folder is blocked, but the more specific /folder/public is allowed.
    txt = "User-agent: *\nDisallow: /folder\nAllow: /folder/public\n"
    rules = parse_robots(txt, UA)
    assert rules.can_fetch("/folder/secret") is False
    assert rules.can_fetch("/folder/public/page") is True

    # Equal-length Allow and Disallow -> Allow wins.
    tie = "User-agent: *\nDisallow: /a\nAllow: /a\n"
    assert parse_robots(tie, UA).can_fetch("/a") is True


def test_wildcard_and_end_anchor():
    txt = "User-agent: *\nDisallow: /*.php$\n"
    rules = parse_robots(txt, UA)
    assert rules.can_fetch("/index.php") is False
    assert rules.can_fetch("/dir/app.php") is False
    assert rules.can_fetch("/index.php?x=1") is True  # $ anchors the end
    assert rules.can_fetch("/index.html") is True


def test_our_group_beats_wildcard_group():
    txt = (
        "User-agent: *\nDisallow: /\n\n"
        "User-agent: minisearch-bot\nDisallow: /private\nAllow: /\n"
    )
    rules = parse_robots(txt, UA)
    # We match our own more-specific group, not the blanket wildcard block.
    assert rules.can_fetch("/public") is True
    assert rules.can_fetch("/private") is False


def test_crawl_delay_parsed():
    txt = "User-agent: *\nCrawl-delay: 2.5\nDisallow: /x\n"
    rules = parse_robots(txt, UA)
    assert rules.crawl_delay == 2.5


def test_comments_and_blank_lines_ignored():
    txt = "# a comment\nUser-agent: *   # inline\nDisallow: /x  # trailing\n\n"
    rules = parse_robots(txt, UA)
    assert rules.can_fetch("/x") is False
    assert rules.can_fetch("/y") is True
