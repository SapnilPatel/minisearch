"""robots.txt parsing with correct longest-match semantics.

Hand-rolled rather than using ``urllib.robotparser`` so we get two things the
stdlib handles poorly: RFC 9309 longest-match rule selection (with Allow winning
ties) and ``Crawl-delay``. Supports ``*`` wildcards and ``$`` end-anchors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class _Rule:
    allow: bool
    length: int          # length of the source pattern = its specificity
    matcher: re.Pattern


def _compile(pattern: str) -> re.Pattern:
    """Translate a robots path pattern into an anchored regex.

    ``*`` matches any run of characters; a trailing ``$`` anchors the end. All
    other regex metacharacters are escaped so they match literally.
    """
    anchor_end = pattern.endswith("$")
    if anchor_end:
        pattern = pattern[:-1]
    regex = "^" + re.escape(pattern).replace(r"\*", ".*")
    if anchor_end:
        regex += "$"
    return re.compile(regex)


@dataclass
class RobotsRules:
    """The rules that apply to *our* crawler for one host."""

    rules: list[_Rule] = field(default_factory=list)
    crawl_delay: float | None = None

    def can_fetch(self, path: str) -> bool:
        """True iff ``path`` (path + optional ``?query``) is allowed.

        Longest matching rule wins; on a length tie, Allow beats Disallow. With
        no matching rule the default is allow.
        """
        best_len = -1
        allowed = True
        for rule in self.rules:
            if rule.matcher.match(path) and (
                rule.length > best_len or (rule.length == best_len and rule.allow)
            ):
                best_len = rule.length
                allowed = rule.allow
        return allowed


def parse_robots(text: str, user_agent: str) -> RobotsRules:
    """Parse ``text`` and return the rules that apply to ``user_agent``.

    Groups are matched by the longest user-agent token that is a substring of our
    name (case-insensitive), falling back to the ``*`` group.
    """
    groups: list[dict] = []
    current: dict | None = None
    last_was_agent = False

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field_name, _, value = line.partition(":")
        field_name = field_name.strip().lower()
        value = value.strip()

        if field_name == "user-agent":
            # A user-agent line after a rule opens a new group; consecutive
            # user-agent lines share one group.
            if current is None or not last_was_agent:
                current = {"agents": [], "rules": [], "delay": None}
                groups.append(current)
            current["agents"].append(value.lower())
            last_was_agent = True
            continue

        last_was_agent = False
        if current is None:
            continue

        if field_name in ("allow", "disallow"):
            # An empty Disallow/Allow value is "no rule" -> skip it. (An empty
            # Disallow notably means "allow everything", not "block everything".)
            if value:
                current["rules"].append((field_name == "allow", value))
        elif field_name == "crawl-delay":
            try:
                current["delay"] = float(value)
            except ValueError:
                pass

    chosen = _select_group(groups, user_agent.lower())
    if chosen is None:
        return RobotsRules()

    compiled = [_Rule(allow, len(pat), _compile(pat)) for allow, pat in chosen["rules"]]
    return RobotsRules(rules=compiled, crawl_delay=chosen["delay"])


def _select_group(groups: list[dict], our_name: str) -> dict | None:
    best: dict | None = None
    best_score = -1
    star: dict | None = None
    for group in groups:
        for agent in group["agents"]:
            if agent == "*":
                star = group
            elif agent in our_name and len(agent) > best_score:
                best_score = len(agent)
                best = group
    return best if best is not None else star
