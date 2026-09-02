"""
NORMATIVE SPECIFICATION — business time zone + named reporting periods.

ONE date/time contract for the whole product. Every runtime that needs the
current business time or the bounds of "this month" / "mois précédent" / a
custom range MUST derive them from here (directly, in Python, or by porting
this exact logic — the Kotlin port in
`mobile/.../data/fleet/ReportingPeriods.kt` and the desktop importer are
parity-tested against `shared/revenue_cases.json`).

Rules
-----
* BUSINESS_TIMEZONE = Africa/Casablanca. All day/week/month/year boundaries
  are local wall-clock midnights in that zone.
* Every period is the half-open interval [start, end) — start inclusive,
  end exclusive. Adjacent periods never overlap and never gap.
* `now_business()` is the ONLY sanctioned "what time is it" call in business
  logic. Bare `datetime.now()` / `datetime.utcnow()` are forbidden in
  `backend/app` and `desktop/app` (enforced by `test_no_naive_now`).
* Week starts Monday (ISO-8601 / `weekday() == 0`).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

BUSINESS_TIMEZONE_NAME = "Africa/Casablanca"
BUSINESS_TZ = ZoneInfo(BUSINESS_TIMEZONE_NAME)

# The seven presets the dashboard revenue filter offers, plus "custom".
PERIOD_NAMES = (
    "today",
    "yesterday",
    "week",          # this week (Mon 00:00 .. next Mon 00:00)
    "last_week",
    "month",         # this calendar month
    "last_month",
    "year",          # this calendar year
    "last_year",
)


def now_business() -> datetime:
    """Timezone-aware 'now' in the business zone. The only sanctioned clock."""
    return datetime.now(BUSINESS_TZ)


def to_business(dt: datetime) -> datetime:
    """Coerce any datetime to an aware datetime in the business zone.

    A naive datetime is *assumed to already be* business-local (that is how
    every historical row that lost its tzinfo on a SQLite round-trip must be
    read); an aware datetime is converted.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=BUSINESS_TZ)
    return dt.astimezone(BUSINESS_TZ)


def business_date(dt: datetime) -> date:
    """The business-local calendar date a moment falls on."""
    return to_business(dt).date()


def start_of_day(d: date) -> datetime:
    """Aware business-local 00:00:00 of the given date."""
    return datetime.combine(d, time.min, tzinfo=BUSINESS_TZ)


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _add_month(d: date) -> date:
    """First day of the month after the month containing `d`."""
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def period_bounds(name: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Return the half-open [start, end) aware-datetime bounds of a named period.

    `name` must be one of PERIOD_NAMES. Raises ValueError otherwise.
    """
    now = to_business(now) if now is not None else now_business()
    today = now.date()

    if name == "today":
        s = today
        e = today + timedelta(days=1)
    elif name == "yesterday":
        s = today - timedelta(days=1)
        e = today
    elif name == "week":
        s = today - timedelta(days=today.weekday())
        e = s + timedelta(days=7)
    elif name == "last_week":
        this_week = today - timedelta(days=today.weekday())
        s = this_week - timedelta(days=7)
        e = this_week
    elif name == "month":
        s = _month_start(today)
        e = _add_month(today)
    elif name == "last_month":
        this_month = _month_start(today)
        e = this_month
        s = _month_start(this_month - timedelta(days=1))
    elif name == "year":
        s = date(today.year, 1, 1)
        e = date(today.year + 1, 1, 1)
    elif name == "last_year":
        s = date(today.year - 1, 1, 1)
        e = date(today.year, 1, 1)
    else:
        raise ValueError(f"unknown period name: {name!r}")

    return start_of_day(s), start_of_day(e)


def custom_bounds(from_date: date, to_date_inclusive: date) -> tuple[datetime, datetime]:
    """Bounds for a user-picked range.

    The UI presents an *inclusive* end date ("Au: 30/09/2026" means the 30th
    counts). This converts it to the canonical half-open interval by adding
    one day to the end.
    """
    if to_date_inclusive < from_date:
        from_date, to_date_inclusive = to_date_inclusive, from_date
    return start_of_day(from_date), start_of_day(to_date_inclusive + timedelta(days=1))


def parse_iso_date(s: str) -> date:
    """Parse a strict ISO `YYYY-MM-DD` date the API contract mandates."""
    return date.fromisoformat(s)


def fmt_display_date(d: date | datetime) -> str:
    """The ONE display format shown to the operator: DD/MM/YYYY."""
    if isinstance(d, datetime):
        d = to_business(d).date()
    return d.strftime("%d/%m/%Y")
