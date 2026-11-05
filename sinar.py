#!/usr/bin/env python3
"""SinarCloud console client — read-only usage, credits and wallet.

Why cookies and not an API key
------------------------------
The dashboard backend (console-api.sinarcloud.com) sits behind a cookie
session. Every /api/* route there answers 401 without it — including routes
that do not exist, because the auth filter runs before routing. The inference
API key (ai.sinarcloud.com) is a different service and has no billing routes.

Login itself is guarded by Cloudflare Turnstile, so it cannot be automated:
you log in once in a browser, copy the request as cURL, and feed it to
`import-curl.sh`. This script then runs headless forever (until the cookie
expires, which it will — there is no refresh token).

Examples
--------
  ./sinar.py                  # human-readable summary
  ./sinar.py --days 7         # 7-day window
  ./sinar.py --json           # raw merged JSON
  ./sinar.py --daily          # table of per-day spend
  ./sinar.py --models         # table of per-model spend
  ./sinar.py --check          # is the cookie still alive?
  ./sinar.py --watch 3        # cron mode: only speak up when runway < 3 days
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

BASE = "https://console-api.sinarcloud.com"
API_VERSION = "1.0"
UA = "sc-api/1.0 (+read-only console client)"
DEFAULT_COOKIE = os.path.expanduser("~/.config/sinarcloud/cookies.txt")


# --------------------------------------------------------------------------
# credentials
# --------------------------------------------------------------------------
def cookie_file() -> str:
    return os.environ.get("SINAR_COOKIE_FILE") or DEFAULT_COOKIE


def load_cookies(path: str) -> tuple[str, bool]:
    """Return (cookie_header, has_session_cookie).

    A jar copied from DevTools also carries analytics cookies (_ga, _fbp,
    twk_uuid_*). They ride along harmlessly, but when the real session cookie
    is absent the request 401s while the file still looks non-empty — so say
    which of the two it is instead of leaving the user guessing.
    """
    if not os.path.exists(path):
        sys.exit(
            f"cookie file not found: {path}\n\n"
            "One-time setup:\n"
            "  1. log in at https://console.sinarcloud.com\n"
            "  2. DevTools -> Network -> any console-api request -> Copy as cURL\n"
            "  3. ./import_cookie.py   (paste, Enter, Ctrl-D)\n"
        )
    raw = open(path, encoding="utf-8").read().strip()
    if not raw:
        sys.exit(f"cookie file is empty: {path}")

    pairs: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:  # Netscape cookies.txt: domain flag path secure expiry name value
            parts = line.split("\t")
            if len(parts) >= 7:
                pairs.append(f"{parts[5]}={parts[6]}")
            continue
        for chunk in line.split(";"):
            chunk = chunk.strip()
            if "=" in chunk:
                pairs.append(chunk)
    if not pairs:
        sys.exit(f"no name=value cookies parsed from {path}")

    names = {p.split("=", 1)[0].strip().lower() for p in pairs}
    has_session = any("session" in n for n in names) or any(
        n in names for n in ("jsessionid", "auth", "access_token", "sid")
    )
    return "; ".join(pairs), has_session


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------
class Client:
    def __init__(self, cookie: str):
        self.cookie = cookie
        self.csrf_name: str | None = None
        self.csrf_token: str | None = None

    def _req(self, path: str, method: str = "GET") -> tuple[int, str]:
        req = urllib.request.Request(BASE + path, method=method)
        req.add_header("Accept", "application/json")
        req.add_header("API-Version", API_VERSION)
        req.add_header("Origin", "https://console.sinarcloud.com")
        req.add_header("Referer", "https://console.sinarcloud.com/")
        req.add_header("User-Agent", UA)
        req.add_header("Cookie", self.cookie)
        if method != "GET":
            self.bootstrap_csrf()
            if self.csrf_name and self.csrf_token:
                req.add_header(self.csrf_name, self.csrf_token)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def bootstrap_csrf(self) -> None:
        if self.csrf_token:
            return
        status, body = self._req("/api/auth/bff/csrf")
        if status != 200:
            sys.exit(f"csrf bootstrap failed: HTTP {status} {body[:200]}")
        doc = json.loads(body)
        self.csrf_name = doc.get("headerName")
        self.csrf_token = doc.get("token")

    def get(self, path: str):
        status, body = self._req(path)
        if status == 401:
            sys.exit(
                "HTTP 401 — session cookie missing or expired.\n"
                "Log in again, then rerun ./import-curl.sh\n"
            )
        if status == 403:
            sys.exit(f"HTTP 403 — {body[:200]}")
        if status != 200:
            return {"_error": f"HTTP {status}", "_body": body[:300]}
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"_error": "unreadable response", "_body": body[:300]}


# --------------------------------------------------------------------------
# endpoints (all GET)
# --------------------------------------------------------------------------
def fetch(client: Client, days: int, with_reports: bool = True) -> dict:
    out: dict = {
        "me": client.get("/api/auth/bff/me"),
        "wallet": client.get("/api/wallet/current"),
        "overview": client.get("/api/ai/usage/overview"),
        "dashboard": client.get(f"/api/ai/usage/dashboard?days={days}"),
    }
    if with_reports:
        out["reports"] = client.get(f"/api/ai/usage/reports?days={days}")
        out["credit_grants"] = client.get("/api/ai/credits/grants?page=0&size=20")
        out["credit_ledger"] = client.get("/api/ai/credits/ledger?page=0&size=20")
    return out


# --------------------------------------------------------------------------
# formatting helpers
# --------------------------------------------------------------------------
def money(obj) -> str:
    """{'amount':'18113.60','currency':'IDR'} -> 'IDR 18,114'."""
    if not isinstance(obj, dict):
        return "—"
    try:
        return f"{obj.get('currency','')} {float(obj.get('amount')):,.0f}".strip()
    except (TypeError, ValueError):
        return "—"


def it(n) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "—"


def ci(limit: float = 7.0) -> str:
    """Return '  ⚠️  SALDO MENIPIS' when runway is under `limit` days."""
    return "  ⚠️  SALDO MENIPIS" if 0 <= limit else ""


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_summary(data: dict) -> None:
    w = data.get("wallet") or {}
    r = data.get("reports") or {}
    o = data.get("overview") or {}

    if "availableBalance" in w:
        print(f"Saldo          : {w.get('currency','')} {float(w['availableBalance']):,.0f}")
        if float(w.get("reservedBalance") or 0):
            print(f"Ditahan        : {w.get('currency','')} {float(w['reservedBalance']):,.0f}")
    else:
        print(f"Saldo          : (gagal) {w.get('_error', 'no data')}")

    f = r.get("forecast") or {}
    if f.get("status") == "READY":
        print(f"Rata-rata/hari : {money(f.get('averageDailyCharge'))}")
        print(f"Bulan berjalan : {money(f.get('monthToDateCharge'))}")
        print(f"Proyeksi bulan : {money(f.get('projectedMonthCharge'))}")
        runway = f.get("runwayDays")
        if runway not in (None, ""):
            days = float(runway)
            print(f"Sisa bertahan : {days:.1f} hari{ci(7) if days < 7 else ''}")

    t = o.get("totals") or {}
    if t:
        print()
        print(f"Request 5 hari : {it(t.get('requests'))}")
        print(f"Token          : masuk {it(t.get('inputTokens'))} / keluar {it(t.get('outputTokens'))}")
        print(f"Total terpakai : {money(t.get('charge'))}")

    cg = data.get("credit_grants") or {}
    total = cg.get("totalElements")
    items = cg.get("content") or []
    if items:
        print(f"\nToken credits  : {len(items)} grant aktif")
        for g in items[:5]:
            print(f"  • {g.get('model','?')} — {it(g.get('remainingTokens', g.get('tokens','?')))} token")
    else:
        suffix = "" if total is None else f" (total {total})"
        print(f"\nToken credits  : tidak ada{suffix}")

    for k in ("overview", "reports", "wallet"):
        v = data.get(k) or {}
        if isinstance(v, dict) and v.get("_error"):
            print(f"\n⚠️  {k}: {v['_error']} — {v.get('_body','')[:120]}")


def cmd_daily(data: dict) -> None:
    """Per-day table.

    `overview.daily` carries request/token counts but no per-day charge;
    `reports.spending` has the money but no daily breakdown. So print the
    counts and flag clearly that the money column is not reported per day —
    inventing an allocation from the monthly total would be a lie.
    """
    rows = (data.get("reports") or {}).get("spending", {}).get("daily") or []
    priced = bool(rows)
    if not rows:
        rows = (data.get("overview") or {}).get("daily") or []
    if not rows:
        sys.exit("no daily data returned")

    if priced:
        print(f"{'tanggal':<12}{'request':>10}{'token':>16}{'biaya':>16}")
        print("-" * 54)
    else:
        print(f"{'tanggal':<12}{'request':>10}{'token':>16}")
        print("-" * 38)

    for row in rows:
        line = f"{row.get('date','?'):<12}{it(row.get('requests')):>10}{it(row.get('totalTokens')):>16}"
        if priced:
            ch = row.get("charge") or {}
            try:
                line += f"{float(ch.get('amount') or 0):>16,.0f}"
            except (TypeError, ValueError):
                line += f"{'—':>16}"
        print(line)

    if not priced:
        total = ((data.get("overview") or {}).get("totals") or {}).get("charge") or {}
        print("-" * 38)
        print(f"catatan: API tidak menyediakan biaya per hari. Total {money(total)} untuk seluruh periode.")


def cmd_models(data: dict) -> None:
    r = data.get("reports") or {}
    perf = r.get("modelPerformance") or []
    if not perf:
        sys.exit("no per-model data returned")
    print(f"{'model':<38}{'request':>9}{'biaya':>18}")
    print("-" * 65)
    for m in perf:
        alias = (m.get("model") or {}).get("alias", "?")
        print(f"{alias[:37]:<38}{it(m.get('requests')):>9}{money(m.get('charge')):>18}")


def cmd_check(client: Client) -> None:
    me = client.get("/api/auth/bff/me")
    if me.get("_error"):
        sys.exit(f"session not usable: {me['_error']}")
    org = (me.get("organization") or {}).get("role", "?")
    print(f"OK — {me.get('email')} ({me.get('displayName')}) · role={org} · tz={me.get('timeZone')}")


def cmd_watch(data: dict, threshold: float) -> int:
    """Cron mode: silent when healthy, one line when the balance runs low."""
    w = data.get("wallet") or {}
    f = ((data.get("reports") or {}).get("forecast")) or {}
    try:
        balance = float(w.get("availableBalance"))
    except (TypeError, ValueError):
        print("WARN: wallet unavailable")
        return 1
    runway = f.get("runwayDays")
    if runway in (None, ""):
        print(f"balance {w.get('currency','')} {balance:,.0f} (no forecast)")
        return 0
    days = float(runway)
    if days < threshold:
        print(
            f"⚠️ SinarCloud: saldo {w.get('currency','')} {balance:,.0f}, "
            f"runway {days:.1f} hari (rata-rata {money(f.get('averageDailyCharge'))}/hari). "
            f"Top up: https://console.sinarcloud.com/billing/top-up"
        )
        return 0
    return 0  # healthy -> silent


# --------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(
        prog="sinar.py",
        description="SinarCloud read-only usage & credit client (cookie session).",
    )
    ap.add_argument("--days", type=int, default=30, choices=[7, 30], help="window for usage data (default 30)")
    ap.add_argument("--json", action="store_true", help="dump merged raw JSON")
    ap.add_argument("--daily", action="store_true", help="per-day spend table")
    ap.add_argument("--models", action="store_true", help="per-model spend table")
    ap.add_argument("--check", action="store_true", help="verify the cookie session only")
    ap.add_argument("--watch", type=float, metavar="DAYS", help="cron mode: print only when runway < DAYS")
    args = ap.parse_args()

    cookie, has_session = load_cookies(cookie_file())
    if not has_session:
        print(
            "PERINGATAN: file cookie ada isinya, tapi tidak ada cookie sesi di dalamnya\n"
            "(hanya cookie analitik seperti _ga/_fbp). Kemungkinan besar kamu\n"
            "meng-copy dari request yang salah, atau sesinya sudah habis.\n"
            "Login ulang lalu jalankan import-curl.sh lagi.\n",
            file=sys.stderr,
        )
    client = Client(cookie)

    if args.check:
        cmd_check(client)
        return

    data = fetch(client, args.days)

    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.watch is not None:
        cmd_watch(data, args.watch)
    elif args.daily:
        cmd_daily(data)
    elif args.models:
        cmd_models(data)
    else:
        cmd_summary(data)


if __name__ == "__main__":
    main()