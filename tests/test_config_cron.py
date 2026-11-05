#!/usr/bin/env python3
"""Offline tests for config and cron helpers.

    python3 tests/test_config_cron.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scapi import cron  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def test_schedule() -> None:
    print("schedule")
    check("every 1", cron.schedule(1) == "* * * * *", cron.schedule(1))
    check("every 5", cron.schedule(5) == "*/5 * * * *", cron.schedule(5))
    check("every 10", cron.schedule(10) == "*/10 * * * *", cron.schedule(10))
    check("every 30", cron.schedule(30) == "*/30 * * * *", cron.schedule(30))
    for bad in (7, 8, 45, 60, 0, -1):
        try:
            cron.schedule(bad)
            check(f"rejects {bad}", False, "accepted")
        except ValueError:
            check(f"rejects {bad}", True)


def test_crontab_editing() -> None:
    print("crontab editing")
    original = (
        "* * * * * /usr/local/bin/wifi-watch >/dev/null 2>&1\n"
        "* * * * * /home/u/.hermes/scripts/netwatch.sh >/dev/null 2>&1\n"
    )
    line = cron.build_line(5, "/home/u/sc-api")
    merged = original + f"{cron.MARKER}\n{line}\n"

    block = cron.managed_lines(merged)
    check("marker found", bool(block), str(block))
    check("two managed lines", len(block) == 2)
    check("schedule parsed back", cron.parse_interval(merged) == 5, str(cron.parse_interval(merged)))

    stripped = cron.without_managed(merged)
    check("unrelated entries kept", "wifi-watch" in stripped and "netwatch" in stripped)
    check("our line removed", "sc-api watch" not in stripped)
    check("no stranded marker", cron.MARKER not in stripped)

    # reinstalling must not duplicate
    again = cron.without_managed(merged) + f"\n{cron.MARKER}\n{cron.build_line(15, '/home/u/sc-api')}\n"
    check("reinstall leaves one entry", again.count(cron.MARKER) == 1, str(again))
    check("reinstall updates interval", cron.parse_interval(again) == 15, str(cron.parse_interval(again)))

    # legacy unmarked entry gets cleaned up
    legacy = original + "*/10 * * * * /home/u/.hermes/scripts/sinarcloud-watch.sh >/dev/null 2>&1\n"
    cleaned = cron.without_managed(legacy)
    check("legacy entry removed", "sinarcloud-watch.sh" not in cleaned, cleaned)


if __name__ == "__main__":
    test_schedule()
    test_crontab_editing()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILED: {', '.join(FAILS)}")
        sys.exit(1)
    print("all config/cron tests passed")