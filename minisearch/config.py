"""Application configuration for minisearch.

Loaded once at startup from environment variables (and an optional local
``.env`` file). Every tunable that the ingest and query paths need lives here so
there is a single, typed source of truth rather than scattered ``os.getenv``
calls throughout the codebase.

The object is frozen (immutable) on purpose: config is read at startup and never
mutated, so making it read-only removes a whole class of "who changed this at
runtime?" bugs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


def _split_csv(raw: str | None) -> list[str]:
    """Parse a comma-separated env value into a normalized list.

    Hosts are lowercased and stripped so ``ALLOWED_DOMAINS=Books.ToScrape.com``
    and ``books.toscrape.com`` behave identically. Empty entries are dropped.
    """
    if not raw:
        return []
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


# These return None when the variable is unset/empty. from_env() then simply
# omits those keys and lets the dataclass supply the default — so the default
# values live in exactly one place (the field declarations), never duplicated.
def _env_str(name: str) -> str | None:
    raw = os.getenv(name)
    return raw if raw not in (None, "") else None


def _env_int(name: str) -> int | None:
    raw = os.getenv(name)
    return int(raw) if raw not in (None, "") else None


def _env_float(name: str) -> float | None:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else None


@dataclass(frozen=True, slots=True)
class Config:
    """Typed, immutable application configuration."""

    # --- Crawl safety -------------------------------------------------------
    # Hard allowlist of hosts the crawler may fetch. Empty means "crawl nothing"
    # — a deliberately safe default so an unconfigured run cannot hit the network.
    allowed_domains: list[str] = field(default_factory=list)
    user_agent: str = (
        "minisearch-bot/0.1 (+https://github.com/SapnilPatel/minisearch)"
    )

    # --- Fetcher pool (Milestone 3) -----------------------------------------
    fetcher_workers: int = 8
    request_timeout_s: float = 10.0
    max_page_bytes: int = 5 * 1024 * 1024
    max_retries: int = 3
    # Base for exponential backoff between retries (base * 2^attempt + jitter).
    retry_base_delay_s: float = 0.5

    # --- Frontier (Milestone 2) ---------------------------------------------
    max_frontier_size: int = 100_000
    per_host_delay_s: float = 1.0

    # --- Dedup (Milestone 4) ------------------------------------------------
    # Bloom filter sizing: capacity it is tuned for, and the false-positive
    # rate at that capacity. 1M URLs at 1% costs ~1.2 MB.
    bloom_expected_urls: int = 1_000_000
    bloom_target_fpr: float = 0.01

    # --- Store / Postgres (Milestone 6) -------------------------------------
    database_url: str = "postgresql://localhost:5432/minisearch"

    # --- Ranking (Milestone 7) ----------------------------------------------
    # BM25 tunables: k1 controls term-frequency saturation, b controls
    # document-length normalization. Literature defaults.
    bm25_k1: float = 1.5
    bm25_b: float = 0.75

    # --- API (Milestone 8) --------------------------------------------------
    api_host: str = "127.0.0.1"
    api_port: int = 8080

    @classmethod
    def from_env(cls, *, load_dotenv_file: bool = True) -> Config:
        """Build a Config from the environment.

        When ``load_dotenv_file`` is True (the default) a local ``.env`` file is
        loaded first, so developers get their overrides without exporting vars by
        hand. Tests pass ``load_dotenv_file=False`` to stay hermetic.
        """
        if load_dotenv_file:
            load_dotenv()

        # Collect only the values actually present in the environment; anything
        # omitted falls back to the field default declared above.
        kwargs: dict[str, object] = {}

        def _set(key: str, value: object) -> None:
            if value is not None:
                kwargs[key] = value

        # `[] or None` -> None, so an empty ALLOWED_DOMAINS keeps the safe default.
        _set("allowed_domains", _split_csv(os.getenv("ALLOWED_DOMAINS")) or None)
        _set("user_agent", _env_str("USER_AGENT"))
        _set("fetcher_workers", _env_int("FETCHER_WORKERS"))
        _set("request_timeout_s", _env_float("REQUEST_TIMEOUT_S"))
        _set("max_page_bytes", _env_int("MAX_PAGE_BYTES"))
        _set("max_retries", _env_int("MAX_RETRIES"))
        _set("retry_base_delay_s", _env_float("RETRY_BASE_DELAY_S"))
        _set("max_frontier_size", _env_int("MAX_FRONTIER_SIZE"))
        _set("per_host_delay_s", _env_float("PER_HOST_DELAY_S"))
        _set("bloom_expected_urls", _env_int("BLOOM_EXPECTED_URLS"))
        _set("bloom_target_fpr", _env_float("BLOOM_TARGET_FPR"))
        _set("database_url", _env_str("DATABASE_URL"))
        _set("bm25_k1", _env_float("BM25_K1"))
        _set("bm25_b", _env_float("BM25_B"))
        _set("api_host", _env_str("API_HOST"))
        _set("api_port", _env_int("API_PORT"))

        return cls(**kwargs)

    def is_host_allowed(self, host: str) -> bool:
        """Return True iff ``host`` is on the crawl allowlist.

        This is the safety rail the fetcher (Milestone 3) consults before every
        request. Matching is case-insensitive and covers subdomains, so an
        allowlist entry of ``toscrape.com`` also permits ``books.toscrape.com``.
        """
        if not host:
            return False
        host = host.lower()
        return any(
            host == allowed or host.endswith("." + allowed)
            for allowed in self.allowed_domains
        )
