"""robots.txt parsing and per-host caching (Milestone 1).

Fetches, parses, and caches robots.txt per host, and answers "may I fetch this
URL?" plus the host's Crawl-delay. Being a good citizen is both correct and
something an interviewer will notice.
"""

from minisearch.robots.cache import RobotsCache
from minisearch.robots.parser import RobotsRules, parse_robots

__all__ = ["RobotsCache", "RobotsRules", "parse_robots"]
