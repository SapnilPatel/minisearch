"""The REST API (Milestone 8).

Endpoints: POST /crawl, GET /search, GET /stats, GET /healthz, GET /metrics.
"""

from minisearch.api.server import create_app, main

__all__ = ["create_app", "main"]
