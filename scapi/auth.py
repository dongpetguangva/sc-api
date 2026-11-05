"""Cookie loading and CSRF bootstrap.

The console API authenticates with a browser session cookie. There is no API
key path: `console-api.sinarcloud.com` runs its auth filter before routing, so
even unknown paths answer 401 rather than 404, and `ai.sinarcloud.com` (the
inference host) exposes no billing routes at all.

Cookie files are accepted in three shapes so an import from any DevTools
"Copy as cURL" flavour just works:

    SESSION=abc; XSRF-TOKEN=def          (raw Cookie header)
    <netscape cookies.txt, tab separated>
    SESSION=abc
    XSRF-TOKEN=def                        (one pair per line)
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_COOKIE_PATH = os.path.expanduser("~/.config/sinarcloud/cookies.txt")

# Cookie names that indicate a real authenticated session rather than
# analytics residue (_ga, _fbp, twk_uuid_*).
_SESSION_HINTS = ("session", "jsessionid", "auth", "access_token", "sid")


class CookieError(Exception):
    """The cookie file is missing, empty, or has no session cookie in it."""


@dataclass
class CookieJar:
    header: str
    has_session: bool
    names: list[str]

    @property
    def warning(self) -> str | None:
        if self.has_session:
            return None
        return (
            "cookie file has cookies but none look like a session cookie "
            f"(found: {', '.join(self.names[:6]) or 'none'}). "
            "You probably copied a request to console.sinarcloud.com instead "
            "of console-api.sinarcloud.com."
        )


def cookie_path(explicit: str | None = None) -> str:
    """Resolve the cookie file: explicit arg > $SINAR_COOKIE_FILE > default."""
    return explicit or os.environ.get("SINAR_COOKIE_FILE") or DEFAULT_COOKIE_PATH


def _parse(raw: str) -> list[str]:
    pairs: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:  # Netscape format: domain, flag, path, secure, expiry, name, value
            parts = line.split("\t")
            if len(parts) >= 7:
                pairs.append(f"{parts[5]}={parts[6]}")
            continue
        for chunk in line.split(";"):
            chunk = chunk.strip()
            if "=" in chunk:
                pairs.append(chunk)
    return pairs


def load_cookie(path: str | None = None) -> CookieJar:
    """Read and classify a cookie file. Raises CookieError with actionable text."""
    resolved = cookie_path(path)
    if not os.path.exists(resolved):
        raise CookieError(
            f"cookie file not found: {resolved}\n\n"
            "One-time setup:\n"
            "  1. log in at https://console.sinarcloud.com\n"
            "  2. DevTools -> Network -> any console-api request -> Copy as cURL\n"
            "  3. ./import_cookie.py   (paste, Enter, Ctrl-D)\n"
        )
    raw = open(resolved, encoding="utf-8").read().strip()
    if not raw:
        raise CookieError(f"cookie file is empty: {resolved}")

    pairs = _parse(raw)
    if not pairs:
        raise CookieError(f"no name=value cookies parsed from {resolved}")

    names = [p.split("=", 1)[0].strip() for p in pairs]
    lowered = [n.lower() for n in names]
    has_session = any(any(h in n for h in _SESSION_HINTS) for n in lowered)
    return CookieJar(header="; ".join(pairs), has_session=has_session, names=names)