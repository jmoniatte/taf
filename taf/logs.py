"""Reading and writing the logs, and their text for the editor; no Textual."""

import re
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import groupby

from .message import Inference, parse_message

DAY_HEADER = re.compile(r"^# (\d{4}-\d{2}-\d{2})")
# The message may be empty, as some old logs are, and an editor may trim the space before it
ENTRY = re.compile(r"^\* (\d{2}:\d{2}) -(?: (.*))?$")
# What an entry may look like once mistyped or reformatted: "- 9:00 - x", "  * 10:00 - x"
ENTRY_LIKE = re.compile(r"^\s*[-*+]\s*\d{1,2}:\d{2}")


@dataclass(frozen=True, slots=True)
class Log:
    id: int
    # The line as typed, @duration, @context and +action included
    message: str
    logged_at: datetime
    # The message without them
    text: str
    action: str
    context: str
    # In minutes; None when the message gave none
    duration: int | None


def logs_between(connection: sqlite3.Connection, first: date, last: date) -> list[Log]:
    """The logs from the first day to the last, both included, the last day first."""
    rows = connection.execute(
        "SELECT id, message, logged_at, text, action, context, duration FROM logs"
        " WHERE logged_at >= ? AND logged_at < ? ORDER BY substr(logged_at, 1, 10) DESC, logged_at, id",
        (first.isoformat(), (last + timedelta(days=1)).isoformat()),
    )
    return [
        Log(
            id=row["id"],
            message=row["message"] or "",
            logged_at=datetime.fromisoformat(row["logged_at"]),
            text=row["text"] or "",
            action=row["action"] or "",
            context=row["context"] or "",
            duration=row["duration"],
        )
        for row in rows
    ]


def create_log(
    connection: sqlite3.Connection,
    message: str,
    action: Inference | None = None,
    context: Inference | None = None,
    logged_at: datetime | None = None,
) -> datetime:
    """Store message, its parts read out with the config's rules, logged now unless told when; returns when."""
    now = datetime.now().replace(microsecond=0)
    logged_at = logged_at or now
    parsed = parse_message(message, action, context)
    connection.execute(
        "INSERT INTO logs (message, logged_at, text, action, context, duration, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (message, timestamp(logged_at), parsed.text, parsed.action, parsed.context, parsed.duration, timestamp(now)),
    )
    return logged_at


def replace_days(
    connection: sqlite3.Connection,
    days: list[date],
    entries: list[tuple[datetime, str]],
    action: Inference | None = None,
    context: Inference | None = None,
) -> None:
    """Delete every log of the days, then store the entries (when, message), all or nothing."""
    connection.execute("BEGIN")
    try:
        for day in days:
            connection.execute(
                "DELETE FROM logs WHERE logged_at >= ? AND logged_at < ?",
                (day.isoformat(), (day + timedelta(days=1)).isoformat()),
            )
        for logged_at, message in entries:
            create_log(connection, message, action, context, logged_at)
        # Inside the try: a COMMIT that fails, on a locked database, must not leave the transaction open
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise


def timestamp(moment: datetime) -> str:
    """The way the Ruby fini's Sequel stored times, which sorting and the date filters rely on."""
    return moment.strftime("%Y-%m-%d %H:%M:%S.000000")


def by_day(logs: list[Log]) -> list[tuple[date, list[Log]]]:
    """The logs in runs of one day each, in the order given."""
    return [(day, list(day_logs)) for day, day_logs in groupby(logs, key=lambda log: log.logged_at.date())]


def format_duration(minutes: int | None) -> str:
    """Minutes the way a message gives them: 15m, 1h, 1h45; "" for none."""
    if minutes is None:
        return ""
    hours, rest = divmod(minutes, 60)
    if not hours:
        return f"{rest}m"
    return f"{hours}h{rest:02d}" if rest else f"{hours}h"


def meta_text(action: str, context: str) -> str:
    """[+action @context] as a log line ends with it, without what is missing; "" with neither."""
    meta = " ".join(part for part in (action and f"+{action}", context and f"@{context}") if part)
    return f"[{meta}]" if meta else ""


def render_markdown(logs: list[Log], empty_days: Iterable[date] = ()) -> str:
    """The logs by day for the editor, each as it was typed, the last day first; empty_days get a
    header too, so logs can be written under it:

    # 2026-09-30 - Wednesday
    * 09:00 - Reviewed PR @15m
    """
    logs_by_day = dict(by_day(logs))
    days = []
    for day in sorted({*logs_by_day, *empty_days}, reverse=True):
        day_logs = logs_by_day.get(day, [])
        lines = [f"# {day} - {day:%A}", *(f"* {log.logged_at:%H:%M} - {log.message}" for log in day_logs), ""]
        days.append("\n".join(lines))
    return "\n".join(days)


def parse_markdown(content: str) -> tuple[list[date], list[tuple[datetime, str]]]:
    """The days whose header is in the file, and every entry under one, as (when, message).

    Other lines are ignored; ValueError for a date or time that does not exist, and for a line
    under a day that starts like an entry but is not one, since its day would lose it.
    """
    days: list[date] = []
    entries: list[tuple[datetime, str]] = []
    day = None
    for line in content.splitlines():
        if header := DAY_HEADER.match(line):
            day = _parse(header.group(1), "%Y-%m-%d", f"'{line}' has no valid date").date()
            days.append(day)
        elif day is not None and (entry := ENTRY.match(line)):
            time = _parse(entry.group(1), "%H:%M", f"'{line}' has no valid time").time()
            entries.append((datetime.combine(day, time), entry.group(2) or ""))
        elif day is not None and (line.startswith("* ") or ENTRY_LIKE.match(line)):
            raise ValueError(f"'{line}' is not a log, '* HH:MM - message'")
    return days, entries


def _parse(value: str, format: str, error: str) -> datetime:
    try:
        return datetime.strptime(value, format)
    except ValueError:
        raise ValueError(error) from None
