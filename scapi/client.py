"""HTTP transport for the SinarCloud console API.

Every request is a GET except the CSRF bootstrap, which is the only
unauthenticated route and never mutates state either. Nothing in this module
can write to an account — there is deliberately no generic `post()` surface.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .auth import CookieJar

BASE_URL = "https://console-api.sinarcloud.com"
API_VERSION = "1.0"
USER_AGENT = "sc-api/1.0 (+read-only console client)"
TIMEOUT = 30


class ApiError(Exception):
    """Non-2xx response that is not an auth failure."""

    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body[:200]}")


class AuthError(ApiError):
    """401/403 — the session cookie is missing or expired."""


class Client:
    """Thin, dependency-free console API client.

    Usage:
        client = Client(load_cookie())
        wallet = client.wallet()
        usage = client.usage(days=30)
    """

    def __init__(self, cookie: "CookieJar | str", base_url: str = BASE_URL):
        # CookieJar is imported here (not at module scope) so `scapi.models`
        # stays usable without touching the HTTP layer.
        from .auth import CookieJar

        self._cookie = cookie.header if isinstance(cookie, CookieJar) else cookie
        self.base_url = base_url.rstrip("/")
        self._csrf_name: str | None = None
        self._csrf_token: str | None = None

    # -- transport ---------------------------------------------------------
    def _request(self, path: str, method: str = "GET") -> str:
        req = urllib.request.Request(self.base_url + path, method=method)
        req.add_header("Accept", "application/json")
        req.add_header("API-Version", API_VERSION)
        req.add_header("Origin", "https://console.sinarcloud.com")
        req.add_header("Referer", "https://console.sinarcloud.com/")
        req.add_header("User-Agent", USER_AGENT)
        req.add_header("Cookie", self._cookie)
        if method != "GET":
            self._bootstrap_csrf()
            if self._csrf_name and self._csrf_token:
                req.add_header(self._csrf_name, self._csrf_token)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.read().decode()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode(errors="replace")
            if exc.code in (401, 403):
                raise AuthError(
                    exc.code,
                    body
                    if exc.code == 403
                    else "session cookie missing or expired — log in again and rerun import_cookie.py",
                ) from None
            raise ApiError(exc.code, body) from None
        except urllib.error.URLError as exc:
            raise ApiError(0, f"cannot reach {self.base_url}: {exc.reason}") from None

    def get(self, path: str) -> dict[str, Any]:
        body = self._request(path)
        if not body:
            return {}
        try:
            doc = json.loads(body)
        except json.JSONDecodeError:
            raise ApiError(0, f"unreadable JSON from {path}: {body[:200]}") from None
        return doc if isinstance(doc, dict) else {"items": doc}

    def _bootstrap_csrf(self) -> None:
        if self._csrf_token:
            return
        doc = self.get("/api/auth/bff/csrf")
        self._csrf_name = doc.get("headerName")
        self._csrf_token = doc.get("token")

    # -- endpoints ---------------------------------------------------------
    # One method per route. Adding a feature means adding one method here,
    # not editing the CLI.

    def me(self) -> dict[str, Any]:
        """Identity, organisation, timezone."""
        return self.get("/api/auth/bff/me")

    def wallet(self) -> dict[str, Any]:
        """availableBalance, reservedBalance, currency, status."""
        return self.get("/api/wallet/current")

    def overview(self) -> dict[str, Any]:
        """Account-wide totals plus a per-day breakdown (requests/tokens only)."""
        return self.get("/api/ai/usage/overview")

    @staticmethod
    def _usage_query(days: int, model: str | None, api_key_id: str | None) -> str:
        params = [f"days={days}"]
        if model:
            params.append(f"model={model}")
        if api_key_id:
            params.append(f"apiKeyId={api_key_id}")
        return "&".join(params)

    def usage(self, days: int = 30, model: str | None = None, api_key_id: str | None = None) -> dict[str, Any]:
        """Dashboard payload: totals, daily[], models[], apiKeys[], recentRequests[]."""
        return self.get("/api/ai/usage/dashboard?" + self._usage_query(days, model, api_key_id))

    def reports(self, days: int = 30, model: str | None = None, api_key_id: str | None = None) -> dict[str, Any]:
        """Forecast (runway), modelPerformance[], spending, promotionSavings."""
        return self.get("/api/ai/usage/reports?" + self._usage_query(days, model, api_key_id))

    def credit_grants(self, page: int = 0, size: int = 20) -> dict[str, Any]:
        return self.get(f"/api/ai/credits/grants?page={page}&size={size}")

    def credit_ledger(self, page: int = 0, size: int = 20) -> dict[str, Any]:
        return self.get(f"/api/ai/credits/ledger?page={page}&size={size}")

    def api_keys(self) -> list[dict[str, Any]]:
        """API keys as embedded in the usage dashboard payload."""
        return self.usage(days=7).get("apiKeys") or []