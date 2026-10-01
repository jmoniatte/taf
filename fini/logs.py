"""Reading the logs from the database; no Textual."""

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import groupby


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
    since = (today or date.today()) - timedelta(days=days - 1)
    rows = connection.execute(
        "SELECT id, message, logged_at, text, action, context, duration FROM logs"
        " WHERE logged_at >= ? ORDER BY substr(logged_at, 1, 10) DESC, logged_at, id",
        (since.isoformat(),),
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
