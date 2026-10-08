import sqlite3
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from taf.database import open_database
from taf.logs import Log, create_log, format_duration, logs_between, meta_text, parse_markdown, render_markdown, replace_days


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
        self.assertEqual([meta_text("code", "rails"), meta_text("", "rails"), meta_text("code", ""), meta_text("", "")], ["[+code @rails]", "[@rails]", "[+code]", ""])


class MarkdownTest(unittest.TestCase):
    def test_markdown_round_trip(self) -> None:
        logs = [
            Log(2, "Coded @2h", datetime(2026, 9, 30, 11, 0), "Coded", "code", "rails", 120),
            Log(1, "Met @1h", datetime(2026, 9, 29, 9, 5), "Met", "meet", "rails", 60),
        ]
        markdown = render_markdown(logs)
        self.assertEqual(markdown, "# 2026-09-30 - Wednesday\n* 11:00 - Coded @2h\n\n# 2026-09-29 - Tuesday\n* 09:05 - Met @1h\n")
        self.assertEqual(
            parse_markdown("* 08:00 - before any day\n" + markdown),
            ([date(2026, 9, 30), date(2026, 9, 29)], [(datetime(2026, 9, 30, 11, 0), "Coded @2h"), (datetime(2026, 9, 29, 9, 5), "Met @1h")]),
        )
        # A log with no message is kept, its space trimmed or not; a broken entry under a day is an error
        self.assertEqual(
            parse_markdown("# 2026-09-30\n* 11:00 - \n* 12:00 -\n"),
            ([date(2026, 9, 30)], [(datetime(2026, 9, 30, 11, 0), ""), (datetime(2026, 9, 30, 12, 0), "")]),
        )
        with self.assertRaisesRegex(ValueError, r"'\* 9:00 - Met' is not a log"):
            parse_markdown("# 2026-09-30\n* 9:00 - Met\n")
        for line in ("- 09:00 - formatted", "  * 10:00 - indented", "*\t11:00 - tab"):
            with self.assertRaisesRegex(ValueError, "is not a log"):
                parse_markdown(f"# 2026-09-30\n{line}\n")
        self.assertEqual(parse_markdown("* 9:00 - before any day\nA note\n"), ([], []))
        # An empty day gets a header too, in its place among the others
        self.assertEqual(
            render_markdown(logs, [date(2026, 10, 1), date(2026, 9, 30)]),
            "# 2026-10-01 - Thursday\n\n# 2026-09-30 - Wednesday\n* 11:00 - Coded @2h\n\n# 2026-09-29 - Tuesday\n* 09:05 - Met @1h\n",
        )


class ReplaceDaysTest(unittest.TestCase):
    def test_a_failed_commit_rolls_back_and_leaves_no_transaction_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            connection = open_database(Path(tmp) / "taf.sqlite3")
            self.addCleanup(connection.close)
            create_log(connection, "Kept @1h", logged_at=datetime(2026, 9, 30, 9, 0))
            with self.assertRaisesRegex(sqlite3.OperationalError, "locked"):
                replace_days(LockedAtCommit(connection), [date(2026, 9, 30)], [(datetime(2026, 9, 30, 10, 0), "New")])
            self.assertFalse(connection.in_transaction)
            self.assertEqual([log.message for log in logs_between(connection, date(2026, 9, 30), date(2026, 9, 30))], ["Kept @1h"])


if __name__ == "__main__":
    unittest.main()
