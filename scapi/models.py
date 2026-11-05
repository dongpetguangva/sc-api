"""Typed views over the raw API payloads.

The API returns money as `{"amount": "18113.60", "currency": "IDR"}` objects and
nests the useful numbers in different places (balance on the wallet route,
runway inside reports.forecast). These dataclasses normalise that once so
callers never re-derive field paths.

Unknown/extra fields are kept in `.raw` so nothing is lost.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Money:
    amount: float = 0.0
    currency: str = ""
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def parse(cls, obj) -> "Money":
        if isinstance(obj, (int, float)):
            return cls(float(obj), "")
        if not isinstance(obj, dict):
            return cls()
        try:
            amount = float(obj.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        return cls(amount, obj.get("currency", ""), obj)

    def __str__(self) -> str:
        return f"{self.currency} {self.amount:,.0f}".strip()

    def __float__(self) -> float:
        return self.amount


@dataclass
class Wallet:
    available: float = 0.0
    reserved: float = 0.0
    currency: str = ""
    status: str = ""
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def parse(cls, doc: dict) -> "Wallet":
        doc = doc if isinstance(doc, dict) else {}
        return cls(
            available=float(doc.get("availableBalance") or 0),
            reserved=float(doc.get("reservedBalance") or 0),
            currency=doc.get("currency", ""),
            status=doc.get("status", ""),
            raw=doc,
        )


@dataclass
class Totals:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    avg_duration_ms: float = 0.0
    charge: Money = field(default_factory=Money)

    @classmethod
    def parse(cls, doc: dict) -> "Totals":
        doc = doc if isinstance(doc, dict) else {}
        return cls(
            requests=int(doc.get("requests") or 0),
            input_tokens=int(doc.get("inputTokens") or 0),
            output_tokens=int(doc.get("outputTokens") or 0),
            total_tokens=int(doc.get("totalTokens") or 0),
            cache_read_tokens=int(doc.get("cacheReadTokens") or 0),
            avg_duration_ms=float(doc.get("averageDurationMs") or 0),
            charge=Money.parse(doc.get("charge")),
        )


@dataclass
class UsageDay:
    date: str
    requests: int
    total_tokens: int
    charge: Money | None = None  # API does not report daily money; usually None


@dataclass
class ModelCost:
    alias: str
    display_name: str
    requests: int
    charge: Money

    @classmethod
    def parse(cls, doc: dict) -> "ModelCost":
        model = doc.get("model") or {}
        return cls(
            alias=model.get("alias", "?"),
            display_name=model.get("displayName", model.get("alias", "?")),
            requests=int(doc.get("requests") or 0),
            charge=Money.parse(doc.get("charge")),
        )


@dataclass
class Forecast:
    status: str = ""
    average_daily: Money = field(default_factory=Money)
    month_to_date: Money = field(default_factory=Money)
    projected_month: Money = field(default_factory=Money)
    runway_days: float | None = None
    observed_days: int = 0

    @classmethod
    def parse(cls, doc: dict) -> "Forecast":
        doc = doc if isinstance(doc, dict) else {}
        runway = doc.get("runwayDays")
        try:
            runway_days = float(runway) if runway not in (None, "") else None
        except (TypeError, ValueError):
            runway_days = None
        return cls(
            status=doc.get("status", ""),
            average_daily=Money.parse(doc.get("averageDailyCharge")),
            month_to_date=Money.parse(doc.get("monthToDateCharge")),
            projected_month=Money.parse(doc.get("projectedMonthCharge")),
            runway_days=runway_days,
            observed_days=int(doc.get("observedDays") or 0),
        )


@dataclass
class Grant:
    model: str
    remaining: int
    expires_at: str | None = None

    @classmethod
    def parse(cls, doc: dict) -> "Grant":
        model = doc.get("model") or {}
        alias = model.get("alias") if isinstance(model, dict) else model
        return cls(
            model=str(alias or "?"),
            remaining=int(doc.get("remainingTokens") or doc.get("tokens") or 0),
            expires_at=doc.get("expiresAt"),
        )


@dataclass
class Snapshot:
    """Everything one refresh needs, in one object."""

    wallet: Wallet
    totals: Totals
    forecast: Forecast
    daily: list[UsageDay] = field(default_factory=list)
    models: list[ModelCost] = field(default_factory=list)
    grants: list[Grant] = field(default_factory=list)
    days: int = 30
    fetched_at: str = ""
    raw: dict = field(default_factory=dict, repr=False)

    # -- derived helpers used by the CLI and the notifier -------------------
    @property
    def balance(self) -> float:
        return self.wallet.available

    @property
    def currency(self) -> str:
        return self.wallet.currency or self.totals.charge.currency

    @property
    def runway_days(self) -> float | None:
        return self.forecast.runway_days

    def below_balance(self, threshold: float) -> bool:
        return self.balance < threshold

    def below_runway(self, days: float) -> bool:
        return self.runway_days is not None and self.runway_days < days