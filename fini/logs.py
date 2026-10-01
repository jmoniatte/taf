"""Reading the logs from the database; no Textual."""

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import groupby

from .message import Inference, parse_message


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


def recent_logs(connection: sqlite3.Connection, days: int, today: date | None = None) -> list[Log]:
    """The logs of the last days, today included, the last day first and each day in the order it
    was logged, as the Ruby fini showed them."""
    today = today or date.today()
    return logs_between(connection, today - timedelta(days=days - 1), today)


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
    except BaseException:
        connection.execute("ROLLBACK")
        raise
    connection.execute("COMMIT")


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
