"""URL canonicalization.

Folds the many spellings of one page down to a single canonical string so that
deduplication works and we do not crawl the same content repeatedly. The parsing
plumbing comes from ``urllib.parse``; the *policy* — which differences are
significant and which are noise — is implemented here and is the interesting part.

See SPEC.md Part 3 §4 for the rationale. The three judgement calls (trailing
slash, ``www.``, http-vs-https) are documented inline where they are applied.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

# Query parameters that identify a marketing campaign or click, not the content.
# Two URLs that differ only in these point at the same page, so we drop them.
TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "gclid",
        "gclsrc",
        "dclid",
        "fbclid",
        "msclkid",
        "mc_cid",
        "mc_eid",
        "yclid",
        "igshid",
        "ref",
        "ref_src",
        "_ga",
    }
)

# Ports implied by the scheme; when present explicitly they are redundant.
DEFAULT_PORTS = {"http": "80", "https": "443", "ws": "80", "wss": "443", "ftp": "21"}

# RFC 3986 "unreserved" characters. A percent-encoded unreserved char (e.g. %7E)
# is equivalent to the char itself (~), so we decode those; everything else stays
# percent-encoded (reserved chars like %2F must NOT be decoded to '/').
_UNRESERVED = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)
_HEX = frozenset("0123456789abcdefABCDEF")


def _normalize_percent_encoding(s: str) -> str:
    """Decode percent-encoded unreserved chars; uppercase the rest's hex digits."""
    out: list[str] = []
    i, n = 0, len(s)
    while i < n:
        if s[i] == "%" and i + 3 <= n and s[i + 1] in _HEX and s[i + 2] in _HEX:
            ch = chr(int(s[i + 1 : i + 3], 16))
            if ch in _UNRESERVED:
                out.append(ch)
            else:
                out.append("%" + s[i + 1 : i + 3].upper())
            i += 3
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _remove_dot_segments(path: str) -> str:
    """RFC 3986 §5.2.4 — resolve ``.`` and ``..`` so ``/a/../b`` becomes ``/b``."""
    out: list[str] = []
    buf = path
    while buf:
        if buf.startswith("../"):
            buf = buf[3:]
        elif buf.startswith("./"):
            buf = buf[2:]
        elif buf.startswith("/./"):
            buf = "/" + buf[3:]
        elif buf == "/.":
            buf = "/"
        elif buf.startswith("/../"):
            buf = "/" + buf[4:]
            if out:
                out.pop()
        elif buf == "/..":
            buf = "/"
            if out:
                out.pop()
        elif buf in (".", ".."):
            buf = ""
        else:
            # Move the first path segment (its leading '/' plus chars up to, but
            # not including, the next '/') to the output.
            start = 1 if buf[0] == "/" else 0
            nxt = buf.find("/", start)
            if nxt == -1:
                out.append(buf)
                buf = ""
            else:
                out.append(buf[:nxt])
                buf = buf[nxt:]
    return "".join(out)


def _normalize_netloc(netloc: str, scheme: str) -> str:
    """Lowercase the host, strip a redundant default port and a trailing dot.

    Userinfo (``user:pass@``) is preserved as-is — it is case-sensitive — and
    IPv6 literals in brackets are left structurally intact.
    """
    if not netloc:
        return netloc

    userinfo = ""
    hostport = netloc
    if "@" in netloc:
        userinfo, hostport = netloc.rsplit("@", 1)
        userinfo += "@"

    if hostport.startswith("["):  # IPv6 literal, e.g. [::1]:8080
        end = hostport.find("]")
        host = hostport[: end + 1].lower()
        rest = hostport[end + 1 :]
        port = rest[1:] if rest.startswith(":") else ""
    elif ":" in hostport:
        host, port = hostport.rsplit(":", 1)
        # NOTE: we keep 'www.' — www.example.com and example.com can be
        # genuinely different hosts, so stripping it would over-fold.
        host = host.lower().rstrip(".")
    else:
        host, port = hostport.lower().rstrip("."), ""

    if port == DEFAULT_PORTS.get(scheme):
        port = ""

    return userinfo + host + (":" + port if port else "")


def _normalize_query(query: str) -> str:
    """Drop tracking params and sort the rest so param order is not significant."""
    if not query:
        return ""
    pairs = parse_qsl(query, keep_blank_values=True)
    kept = [(k, v) for k, v in pairs if k.lower() not in TRACKING_PARAMS]
    kept.sort()
    return urlencode(kept)


def canonicalize(url: str, base: str | None = None) -> str:
    """Return the canonical form of ``url`` (resolved against ``base`` if given).

    Idempotent: ``canonicalize(canonicalize(u)) == canonicalize(u)``.
    """
    if base:
        url = urljoin(base, url)

    parts = urlsplit(url.strip())

    # Scheme and host are case-insensitive; keep the scheme as given otherwise —
    # http and https can address different resources, so we do NOT unify them.
    scheme = parts.scheme.lower()
    netloc = _normalize_netloc(parts.netloc, scheme)

    path = _remove_dot_segments(_normalize_percent_encoding(parts.path))

    # Trailing-slash policy: strip it, EXCEPT for the root path. This folds
    # /a and /a/ together, trading a small risk (a server that serves different
    # content for the two) for fewer duplicate crawls. An empty path on a URL
    # that has a host becomes '/'.
    if not path:
        path = "/" if netloc else ""
    elif path != "/":
        path = path.rstrip("/") or "/"

    query = _normalize_query(parts.query)

    # Fragment is dropped entirely — it is never sent to the server.
    return urlunsplit((scheme, netloc, path, query, ""))
