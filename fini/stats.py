"""Time spent per day, action and month, out of the logs; no Textual."""

import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

# Time off, not work: left out of every figure
TIME_OFF = "pto"


@dataclass(frozen=True, slots=True)
class Entry:
    day: date
    action: str
    # Minutes
    duration: int


@dataclass(frozen=True, slots=True)
class Period:
    label: str
    first: date
    last: date


def load_entries(connection: sqlite3.Connection) -> list[Entry]:
    """Every log with a duration, time off left out, the oldest first."""
    rows = connection.execute(
        "SELECT substr(logged_at, 1, 10) AS day, action, duration FROM logs"
        " WHERE duration IS NOT NULL AND coalesce(action, '') != ? ORDER BY logged_at",
        (TIME_OFF,),
    )
    return [Entry(date.fromisoformat(row["day"]), row["action"] or "", row["duration"]) for row in rows]


def periods(entries: list[Entry], today: date) -> list[Period]:
    """The last 12 months, then each year with logs, the last first, then all of them; none starts
    before the first log."""
    found = [Period("Last 12 months", today - timedelta(days=364), today)]
    if not entries:
        return found
    start = min(entry.day for entry in entries)
    years = sorted({entry.day.year for entry in entries}, reverse=True)
    found += [Period(str(year), max(date(year, 1, 1), start), date(year, 12, 31)) for year in years]
    if len(years) > 1:
        found.append(Period("All time", start, date(years[0], 12, 31)))
    return found


def within(entries: list[Entry], period: Period, action: str | None = None) -> list[Entry]:
    """The entries of the period, of the action only when one is given."""
    return [
        entry
        for entry in entries
        if period.first <= entry.day <= period.last and (action is None or entry.action == action)
    ]


def minutes_by_day(entries: list[Entry]) -> dict[date, int]:
    totals: Counter[date] = Counter()
    for entry in entries:
        totals[entry.day] += entry.duration
    return dict(totals)


def minutes_by_action(entries: list[Entry]) -> list[tuple[str, int]]:
    """Each action and its minutes, the most first."""
    totals: Counter[str] = Counter()
    for entry in entries:
        totals[entry.action] += entry.duration
    return totals.most_common()


def minutes_by_month(entries: list[Entry]) -> list[tuple[date, Counter[str]]]:
    """Each month with logs, the first day standing for it, and its minutes per action, in order."""
    months: defaultdict[date, Counter[str]] = defaultdict(Counter)
    for entry in entries:
        months[entry.day.replace(day=1)][entry.action] += entry.duration
    return sorted(months.items())


def levels(values: list[int]) -> list[int]:
    """The three thresholds between the four shades of a day with logs, as GitHub has them: the
    quartiles of the days with logs."""
    ordered = sorted(value for value in values if value > 0)
    if not ordered:
        return [0, 0, 0]
    return [ordered[len(ordered) * quarter // 4] for quarter in (1, 2, 3)]


def level(minutes: int, thresholds: list[int]) -> int:
    """0 for no logs, else 1 to 4, darker for more time."""
    if minutes <= 0:
        return 0
    return 1 + sum(minutes >= threshold for threshold in thresholds)
