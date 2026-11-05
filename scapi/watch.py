"""Watch mode: refresh on an interval, fire reminders, stay quiet otherwise.

Two outputs, deliberately separate:

  * terminal — a live block redrawn in place (`--watch 600`)
  * `--json`  — one JSON object per tick, for scripts and dashboards
  * `--once`  — a single evaluation, for cron

Reminder state is persisted so a low balance is announced once per side of the
threshold, not on every tick. Without that, a 5-second interval would spam the
channel 12 times a minute.
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field

from .client import AuthError, Client
from .models import Snapshot
from .notify import notify_all
from .report import build_snapshot, format_summary

DEFAULT_STATE = os.path.expanduser("~/.local/state/sinarcloud/state.json")


@dataclass
class WatchConfig:
    interval: float = 60.0            # seconds between refreshes
    balance_threshold: float | None = None   # fire when balance < this
    runway_threshold: float | None = None    # fire when runway_days < this
    days: int = 30                    # reporting window
    notify: bool = True               # allow sending
    once: bool = False                # single tick (cron)
    as_json: bool = False             # one JSON object per tick
    quiet: bool = False               # no terminal output, only notifications
    state_path: str = DEFAULT_STATE
    max_ticks: int = 0                # 0 = forever


@dataclass
class State:
    breached: dict = field(default_factory=dict)   # {"balance": "...", "runway": "..."}
    last_fired: float = 0.0

    @classmethod
    def load(cls, path: str) -> "State":
        if not os.path.exists(path):
            return cls()
        try:
            doc = json.load(open(path, encoding="utf-8"))
            return cls(breached=doc.get("breached") or {}, last_fired=float(doc.get("last_fired") or 0))
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            return cls()

    def save(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"breached": self.breached, "last_fired": self.last_fired}, fh, indent=1)
        os.replace(tmp, path)


def _snapshot_json(snap: Snapshot) -> dict:
    return {
        "fetched_at": snap.fetched_at,
        "balance": snap.balance,
        "currency": snap.currency,
        "reserved": snap.wallet.reserved,
        "runway_days": snap.runway_days,
        "average_daily": snap.forecast.average_daily.amount,
        "projected_month": snap.forecast.projected_month.amount,
        "month_to_date": snap.forecast.month_to_date.amount,
        "requests": snap.totals.requests,
        "input_tokens": snap.totals.input_tokens,
        "output_tokens": snap.totals.output_tokens,
        "charge": snap.totals.charge.amount,
        "credits": [{"model": g.model, "remaining": g.remaining} for g in snap.grants],
    }


def evaluate(snap: Snapshot, cfg: WatchConfig, state: State) -> list[dict]:
    """Return the list of breach dicts for this tick, updating `state`."""
    breaches: list[dict] = []
    if cfg.balance_threshold is not None and snap.below_balance(cfg.balance_threshold):
        breaches.append(
            {
                "kind": "balance",
                "severity": "critical" if snap.balance < cfg.balance_threshold * 0.5 else "warning",
                "balance": snap.balance,
                "threshold": cfg.balance_threshold,
            }
        )
    if cfg.runway_threshold is not None and snap.below_runway(cfg.runway_threshold):
        breaches.append(
            {
                "kind": "runway",
                "severity": "critical" if (snap.runway_days or 0) < cfg.runway_threshold * 0.5 else "warning",
                "runway_days": snap.runway_days,
                "threshold": cfg.runway_threshold,
            }
        )
    return breaches


def _escalate(breach: dict) -> str:
    return f"{breach['severity']}"


def run(client: Client, cfg: WatchConfig) -> int:
    state = State.load(cfg.state_path)
    tick = 0
    while True:
        tick += 1
        try:
            snap = build_snapshot(client, days=cfg.days, with_credits=not cfg.quiet)
        except AuthError as exc:
            print(f"\n{exc}", file=sys.stderr)
            print("Session expired. Re-import the cookie, then restart the watch.", file=sys.stderr)
            return 2

        breaches = evaluate(snap, cfg, state)

        # -- output ------------------------------------------------------
        if cfg.as_json:
            payload = _snapshot_json(snap)
            payload["breaches"] = breaches
            payload["tick"] = tick
            print(json.dumps(payload, ensure_ascii=False), flush=True)
        elif not cfg.quiet:
            if tick > 1:
                # Move the cursor back to the top of the block and clear it.
                sys.stdout.write(f"\r\033[{_BLOCK_LINES}A\033[J")
            sys.stdout.write(format_summary(snap, low_runway=cfg.runway_threshold) + "\n")
            sys.stdout.write(_stamp(cfg.interval, breaches) + "\n")
            sys.stdout.flush()

        # -- reminders (only on state change) ----------------------------
        if cfg.notify and breaches:
            fired_kinds = set(state.breached)
            fresh = [b for b in breaches if b["kind"] not in fired_kinds]
            escalations = [
                b
                for b in breaches
                if b["kind"] in fired_kinds
                and state.breached.get(b["kind"]) != _escalate(b)
            ]
            to_send = fresh + escalations
            if to_send:
                lead = to_send[0]
                results = notify_all(
                    balance=snap.balance,
                    currency=snap.currency,
                    threshold=cfg.balance_threshold or 0,
                    runway_days=snap.runway_days,
                    average_daily=snap.forecast.average_daily.amount,
                    severity=lead["severity"],
                )
                state.last_fired = time.time()
                for kind in {b["kind"] for b in to_send}:
                    state.breached[kind] = _escalate(
                        next(b for b in to_send if b["kind"] == kind)
                    )
                state.save(cfg.state_path)
                if not cfg.quiet and not cfg.as_json:
                    for channel, (ok, detail) in results.items():
                        mark = "✓" if ok else "✗"
                        print(f"  reminder[{channel}] {mark} {detail[:80]}", flush=True)

        # -- clear the flag once healthy again ---------------------------
        if not breaches and state.breached:
            state.breached.clear()
            state.save(cfg.state_path)

        if cfg.once or (cfg.max_ticks and tick >= cfg.max_ticks):
            return 0
        time.sleep(max(1.0, cfg.interval))


_BLOCK_LINES = 13


def _stamp(interval: float, breaches: list[dict]) -> str:
    parts = [f"refresh: {interval:.0f}s", f"{time.strftime('%H:%M:%S')}"]
    if breaches:
        parts.append("STATUS: " + ", ".join(f"{b['kind']}={b['severity']}" for b in breaches))
    else:
        parts.append("STATUS: ok")
    return "  ·  ".join(parts)