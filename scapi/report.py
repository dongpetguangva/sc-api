"""Turn raw API payloads into a Snapshot, and Snapshots into text.

Kept separate from the CLI so anything (a TUI, a web endpoint, a cron script)
can reuse the same rendering without shelling out.
"""

from __future__ import annotations

from .client import Client
from .models import (
    Forecast,
    Grant,
    ModelCost,
    Snapshot,
    Totals,
    UsageDay,
    Wallet,
)


def build_snapshot(client: Client, days: int = 30, with_credits: bool = True) -> Snapshot:
    """Fetch every endpoint needed for one report and normalise it."""
    wallet_doc = client.wallet()
    usage_doc = client.usage(days=days)
    reports_doc = client.reports(days=days)

    daily: list[UsageDay] = []
    spending_daily = (reports_doc.get("spending") or {}).get("daily") or []
    if spending_daily:
        for row in spending_daily:
            daily.append(
                UsageDay(
                    date=row.get("date", "?"),
                    requests=int(row.get("requests") or 0),
                    total_tokens=int(row.get("totalTokens") or 0),
                    charge=None,
                )
            )
    else:
        # The console API reports no per-day money; overview.daily has counts only.
        for row in usage_doc.get("daily") or client.overview().get("daily") or []:
            daily.append(
                UsageDay(
                    date=row.get("date", "?"),
                    requests=int(row.get("requests") or 0),
                    total_tokens=int(row.get("totalTokens") or 0),
                )
            )

    models = [ModelCost.parse(m) for m in (reports_doc.get("modelPerformance") or [])]

    grants: list[Grant] = []
    if with_credits:
        grants_doc = client.credit_grants()
        grants = [Grant.parse(g) for g in (grants_doc.get("content") or [])]

    return Snapshot(
        wallet=Wallet.parse(wallet_doc),
        totals=Totals.parse(usage_doc.get("totals") or {}),
        forecast=Forecast.parse((reports_doc.get("forecast") or {})),
        daily=daily,
        models=models,
        grants=grants,
        days=days,
        fetched_at=(reports_doc.get("to") or ""),
        raw={"usage": usage_doc, "reports": reports_doc, "wallet": wallet_doc},
    )


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------
def _it(n) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "—"


def format_summary(snap: Snapshot, low_runway: float | None = 7.0) -> str:
    w, f, t = snap.wallet, snap.forecast, snap.totals
    cur = snap.currency
    lines = [f"Saldo          : {cur} {w.available:,.0f}".rstrip()]
    if w.reserved:
        lines.append(f"Ditahan        : {cur} {w.reserved:,.0f}")

    if f.status == "READY":
        lines += [
            f"Rata-rata/hari : {f.average_daily}",
            f"Bulan berjalan : {f.month_to_date}",
            f"Proyeksi bulan : {f.projected_month}",
        ]
        if f.runway_days is not None:
            warn = "  ⚠️  SALDO MENIPIS" if low_runway is not None and f.runway_days < low_runway else ""
            lines.append(f"Sisa bertahan : {f.runway_days:.1f} hari{warn}")

    lines += [
        "",
        f"Request        : {_it(t.requests)}",
        f"Token          : masuk {_it(t.input_tokens)} / keluar {_it(t.output_tokens)}",
        f"Total terpakai : {t.charge}",
    ]

    if snap.grants:
        lines.append("")
        lines.append(f"Token credits  : {len(snap.grants)} grant aktif")
        for g in snap.grants[:5]:
            lines.append(f"  • {g.model} — {_it(g.remaining)} token")
    else:
        lines.append("")
        lines.append("Token credits  : tidak ada")

    return "\n".join(lines)


def format_daily(snap: Snapshot) -> str:
    if not snap.daily:
        return "no daily data returned"
    priced = any(d.charge is not None for d in snap.daily)
    head = f"{'tanggal':<12}{'request':>10}{'token':>16}"
    if priced:
        head += f"{'biaya':>16}"
    out = [head, "-" * len(head)]
    for d in snap.daily:
        row = f"{d.date:<12}{_it(d.requests):>10}{_it(d.total_tokens):>16}"
        if priced:
            row += f"{(d.charge or 0):>16,.0f}"
        out.append(row)
    if not priced:
        out.append("-" * len(head))
        out.append(
            f"catatan: API tidak menyediakan biaya per hari. "
            f"Total {snap.totals.charge} untuk seluruh periode."
        )
    return "\n".join(out)


def format_models(snap: Snapshot) -> str:
    if not snap.models:
        return "no per-model data returned"
    head = f"{'model':<38}{'request':>9}{'biaya':>18}"
    out = [head, "-" * 65]
    for m in snap.models:
        out.append(f"{m.alias[:37]:<38}{_it(m.requests):>9}{str(m.charge):>18}")
    return "\n".join(out)