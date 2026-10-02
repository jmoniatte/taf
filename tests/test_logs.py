import sqlite3
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from fini.database import open_database
from fini.logs import create_log, format_duration, logs_between, replace_days


class LockedAtCommit:
    """A connection whose COMMIT fails, as on a database another process keeps locked."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def execute(self, sql: str, *args):
        if sql == "COMMIT":
            raise sqlite3.OperationalError("database is locked")
        return self.connection.execute(sql, *args)


class FormatDurationTest(unittest.TestCase):
    def test_minutes_read_the_way_a_message_gives_them(self) -> None:
        self.assertEqual(
            [format_duration(minutes) for minutes in (None, 0, 15, 60, 105, 125, 600)],
            ["", "0m", "15m", "1h", "1h45", "2h05", "10h"],
        )


class ReplaceDaysTest(unittest.TestCase):
    def test_a_failed_commit_rolls_back_and_leaves_no_transaction_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            connection = open_database(Path(tmp) / "fini.sqlite3")
            self.addCleanup(connection.close)
            create_log(connection, "Kept @1h", logged_at=datetime(2026, 9, 30, 9, 0))
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                replace_days(LockedAtCommit(connection), [date(2026, 9, 30)], [(datetime(2026, 9, 30, 10, 0), "New")])
            self.assertFalse(connection.in_transaction)
            self.assertEqual([log.message for log in logs_between(connection, date(2026, 9, 30), date(2026, 9, 30))], ["Kept @1h"])


if __name__ == "__main__":
    unittest.main()
