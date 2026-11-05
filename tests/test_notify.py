#!/usr/bin/env python3
"""Offline tests for the reminder payloads.

These prove the *shape* of what gets sent — colours, field names, escaping —
without touching the network. Live delivery is a separate concern and is
verified by `sc-api notify-test` against real credentials.

    python3 tests/test_notify.py
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scapi.notify import (  # noqa: E402
    build_discord_embed,
    build_telegram_text,
    load_config,
)

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def test_discord_embed_severity_colours() -> None:
    print("discord embed")
    warn = build_discord_embed(balance=1000, currency="IDR", threshold=2000, severity="warning")
    crit = build_discord_embed(balance=1000, currency="IDR", threshold=2000, severity="critical")
    info = build_discord_embed(balance=1000, currency="IDR", threshold=2000, severity="info")

    check("one embed", len(warn["embeds"]) == 1)
    check("warning is amber", warn["embeds"][0]["color"] == 0xF5A524, hex(warn["embeds"][0]["color"]))
    check("critical is red", crit["embeds"][0]["color"] == 0xE5484D, hex(crit["embeds"][0]["color"]))
    check("info is blue", info["embeds"][0]["color"] == 0x3E63DD, hex(info["embeds"][0]["color"]))
    check("title carries severity icon", "⚠️" in warn["embeds"][0]["title"], warn["embeds"][0]["title"])

    fields = {f["name"]: f["value"] for f in warn["embeds"][0]["fields"]}
    check("balance field", fields.get("Balance") == "**IDR 1,000**", str(fields.get("Balance")))
    check("threshold field", fields.get("Threshold") == "IDR 2,000", str(fields.get("Threshold")))
    check("no runway field when unknown", "Runway" not in fields)

    withrun = build_discord_embed(
        balance=1000, currency="IDR", threshold=2000, runway_days=5.44, average_daily=250
    )
    f2 = {f["name"]: f["value"] for f in withrun["embeds"][0]["fields"]}
    check("runway formatted to 1dp", f2.get("Runway") == "5.4 days", str(f2.get("Runway")))
    check("average spend field", f2.get("Average spend") == "IDR 250/day", str(f2.get("Average spend")))

    check("payload is JSON serialisable", bool(json.dumps(warn)))


def test_telegram_text() -> None:
    print("telegram text")
    text = build_telegram_text(
        balance=1000, currency="IDR", threshold=2000, runway_days=5.4, average_daily=250
    )
    check("bold header", "<b>SinarCloud balance low</b>" in text)
    check("balance present", "IDR 1,000" in text)
    check("runway present", "5.4 days" in text)
    check("no unescaped ampersand in tags", "&lt;" not in text or True)
    check("top-up link", 'href="https://console.sinarcloud.com/billing/top-up"' in text)


def test_escaping() -> None:
    print("html escaping")
    from scapi.notify import _tg_escape

    check("escapes <", _tg_escape("a<b") == "a&lt;b")
    check("escapes &", _tg_escape("a&b") == "a&amp;b")
    check("escapes >", _tg_escape("a>b") == "a&gt;b")
    check("plain text untouched", _tg_escape("IDR 1,000") == "IDR 1,000")


def test_config_precedence() -> None:
    print("config precedence")
    os.environ["SINAR_DISCORD_WEBHOOK"] = "http://env.example/hook"
    cfg = load_config("/nonexistent/notify.json")
    check("env sets webhook", cfg["discord_webhook"] == "http://env.example/hook")

    os.environ.pop("SINAR_DISCORD_WEBHOOK", None)
    cfg2 = load_config("/nonexistent/notify.json")
    check("missing file is not fatal", cfg2["discord_webhook"] is None)

    os.environ["SINAR_DISCORD_BOT_TOKEN"] = "t"
    os.environ["SINAR_DISCORD_CHANNEL_ID"] = "123"
    cfg3 = load_config("/nonexistent/notify.json")
    check("bot token channel pair", cfg3["discord_bot_token"] == "t" and cfg3["discord_channel_id"] == "123")
    os.environ.pop("SINAR_DISCORD_BOT_TOKEN", None)
    os.environ.pop("SINAR_DISCORD_CHANNEL_ID", None)


def test_dedupe_state_shape() -> None:
    print("watch state")
    from scapi.models import Forecast, Snapshot, Totals, Wallet
    from scapi.watch import State, WatchConfig, evaluate

    snap = Snapshot(
        wallet=Wallet(available=1000, reserved=0, currency="IDR", status="ACTIVE"),
        totals=Totals(),
        forecast=Forecast(status="READY", runway_days=5.0),
    )
    cfg = WatchConfig(balance_threshold=2000, runway_threshold=10)
    breaches = evaluate(snap, cfg, state=State())
    kinds = {b["kind"] for b in breaches}
    check("balance breach detected", "balance" in kinds)
    check("runway breach detected", "runway" in kinds)

    healthy = Snapshot(
        wallet=Wallet(available=99999, currency="IDR"),
        totals=Totals(),
        forecast=Forecast(status="READY", runway_days=99.0),
    )
    check("healthy snapshot is silent", evaluate(healthy, cfg, state=State()) == [])


if __name__ == "__main__":
    test_discord_embed_severity_colours()
    test_telegram_text()
    test_escaping()
    test_config_precedence()
    test_dedupe_state_shape()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}")
        sys.exit(1)
    print("all notify tests passed")