"""Tests for the config module.

Config is loaded once at startup and read everywhere, so its parsing and the
crawl-allowlist safety rail are worth testing from the very first milestone.
All tests pass ``load_dotenv_file=False`` (or set env directly) to stay hermetic
— they must not depend on a developer's local .env.
"""

from minisearch.config import Config, _split_csv


def test_split_csv_normalizes_and_drops_blanks():
    assert _split_csv("A.com, b.com ,, C.COM") == ["a.com", "b.com", "c.com"]
    assert _split_csv("") == []
    assert _split_csv(None) == []


def test_defaults_when_env_empty(monkeypatch):
    # Clear anything that could leak in from the real environment.
    for key in ("ALLOWED_DOMAINS", "FETCHER_WORKERS", "PER_HOST_DELAY_S"):
        monkeypatch.delenv(key, raising=False)

    cfg = Config.from_env(load_dotenv_file=False)

    assert cfg.allowed_domains == []
    assert cfg.fetcher_workers == 8
    assert cfg.per_host_delay_s == 1.0


def test_env_overrides_are_typed(monkeypatch):
    monkeypatch.setenv("ALLOWED_DOMAINS", "example.com, Test.ORG")
    monkeypatch.setenv("FETCHER_WORKERS", "16")
    monkeypatch.setenv("PER_HOST_DELAY_S", "0.5")

    cfg = Config.from_env(load_dotenv_file=False)

    assert cfg.allowed_domains == ["example.com", "test.org"]
    assert cfg.fetcher_workers == 16          # parsed as int, not "16"
    assert cfg.per_host_delay_s == 0.5        # parsed as float


def test_empty_allowlist_blocks_every_host():
    # The safe default: an unconfigured crawler may fetch nothing.
    cfg = Config(allowed_domains=[])
    assert cfg.is_host_allowed("example.com") is False


def test_allowlist_matches_host_and_subdomains():
    cfg = Config(allowed_domains=["toscrape.com"])
    assert cfg.is_host_allowed("toscrape.com") is True
    assert cfg.is_host_allowed("books.toscrape.com") is True   # subdomain allowed
    assert cfg.is_host_allowed("BOOKS.TOSCRAPE.COM") is True    # case-insensitive
    assert cfg.is_host_allowed("nottoscrape.com") is False      # not a real suffix
    assert cfg.is_host_allowed("evil.com") is False
    assert cfg.is_host_allowed("") is False
