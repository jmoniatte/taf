import io
import re
import shlex
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from travail.config import Config
from travail.database import open_database
from travail.log_command import parse_markdown, render_markdown, render_terminal, run
from travail.logs import Log, create_log, logs_between
from travail.message import Inference

TODAY = date(2026, 9, 30)
RULES = {
    "action": Inference("code", [("meet", [re.compile(r"^Met\b")])]),
    "context": Inference("rails", [("public-api", [re.compile(r"(?i)\bpublic api\b")])]),
}


def python_editor(code: str) -> str:
    """An $EDITOR that runs Python on the file, whose path is sys.argv[1]."""
    return shlex.join([sys.executable, "-c", code])


class TerminalOutput(io.StringIO):
    def isatty(self) -> bool:
        return True


class LogCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config = Config(database_path=Path(tmp.name) / "travail.sqlite3", **RULES)
        self.tmp = Path(tmp.name)

    def run_command(self, out=None, **kwargs) -> str:
        out = out or io.StringIO()
        self.assertEqual(run(self.config, today=TODAY, out=out, **kwargs), 0)
        return out.getvalue()

    def add(self, logged_at: str, message: str) -> None:
        connection = open_database(self.config.database_path)
        create_log(connection, message, self.config.action, self.config.context, datetime.fromisoformat(logged_at))
        connection.close()

    def stored(self) -> list[tuple]:
        connection = open_database(self.config.database_path)
        rows = [(f"{log.logged_at:%Y-%m-%d %H:%M}", log.message, log.text, log.action, log.context, log.duration) for log in logs_between(connection, date(2000, 1, 1), date(2100, 1, 1))]
        connection.close()
        return rows

    def test_a_message_is_logged_now_with_its_parts_and_its_day_shown(self) -> None:
        output = self.run_command(message="Met with Brian about the public API @1h30")
        [row] = self.stored()
        self.assertEqual(row[1:], ("Met with Brian about the public API @1h30", "Met with Brian about the public API", "meet", "public-api", 90))
        self.assertEqual(row[0], f"{datetime.now():%Y-%m-%d %H:%M}")
        self.assertIn("- Met with Brian about the public API 1h30 [+meet @public-api]", output)
        connection = sqlite3.connect(self.config.database_path)
        logged_at, created_at = connection.execute("SELECT logged_at, created_at FROM logs").fetchone()
        connection.close()
        # Stored the way Sequel stored them
        self.assertRegex(logged_at, r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.000000$")
        self.assertEqual(logged_at, created_at)

    def test_view_shows_the_last_days_like_the_ruby_fini_and_today_by_default(self) -> None:
        self.add("2026-09-28 09:00", "Too old @1h")
        self.add("2026-09-29 10:00", "Reviewed PR +review @20m")
        self.add("2026-09-30 11:00", "Coded @2h")
        self.add("2026-09-30 09:00", "Met for sync @1h15")
        self.add("2026-10-01 09:00", "Tomorrow")
        expected = (
            "2026-09-30 - Wednesday 3h15\n"
            "* 09:00 - Met for sync 1h15 [+meet @rails]\n"
            "* 11:00 - Coded 2h [+code @rails]\n"
            "\n"
            "2026-09-29 - Tuesday 20m\n"
            "* 10:00 - Reviewed PR 20m [+review @rails]\n"
            "\n"
        )
        self.assertEqual(self.run_command(view=2), expected)
        self.assertEqual(self.run_command(), expected.split("\n\n")[0] + "\n\n")
        # In a terminal: the screen cleared first, and the Ruby fini's colors
        colored = self.run_command(out=TerminalOutput())
        self.assertTrue(colored.startswith("\033[H\033[2J\033[3J\033[31m2026-09-30 - Wednesday\033[0m \033[36m3h15\033[0m\n"))
        self.assertIn("\033[1mCoded\033[0m \033[36m2h\033[0m \033[3m\033[37m[+code @rails]\033[0m\033[0m\n", colored)

    def test_edit_replaces_the_days_left_in_the_file_with_its_entries(self) -> None:
        self.add("2026-09-29 10:00", "Reviewed PR +review @20m")
        self.add("2026-09-30 09:00", "Met for sync @1h15")
        self.add("2026-09-30 11:00", "Coded @2h")
        def edit(code: str) -> str:
            # Keeps what the editor was given, then changes the file
            return python_editor(
                "import sys, pathlib; path = pathlib.Path(sys.argv[1]); "
                f"open({str(self.tmp / 'seen.md')!r}, 'w').write(path.read_text()); {code}"
            )

        # Today: one log changed, one dropped, one added; yesterday's header is gone, so its log stays
        code = (
            "path.write_text('# 2026-09-30 - Wednesday\\n* 09:00 - Met for sync @1h\\n* 14:30 - Emailed about the public API @15m\\n"
            "stray line\\n')"
        )
        with patch.dict("os.environ", {"EDITOR": edit(code)}):
            output = self.run_command(edit=2)
        self.assertEqual(
            (self.tmp / "seen.md").read_text(),
            "# 2026-09-30 - Wednesday\n* 09:00 - Met for sync @1h15\n* 11:00 - Coded @2h\n\n# 2026-09-29 - Tuesday\n* 10:00 - Reviewed PR +review @20m\n",
        )
        self.assertEqual(
            self.stored(),
            [
                ("2026-09-30 09:00", "Met for sync @1h", "Met for sync", "meet", "rails", 60),
                ("2026-09-30 14:30", "Emailed about the public API @15m", "Emailed about the public API", "code", "public-api", 15),
                ("2026-09-29 10:00", "Reviewed PR +review @20m", "Reviewed PR", "review", "rails", 20),
            ],
        )
        self.assertTrue(output.endswith("✓ Logs updated for 2026-09-29 to 2026-09-30\n"))

        # A time that does not exist saves nothing and keeps the file
        with patch.dict("os.environ", {"EDITOR": python_editor("import sys; open(sys.argv[1], 'w').write('# 2026-09-30\\n* 25:00 - Late\\n')")}):
            with patch("sys.stderr", new=io.StringIO()) as error:
                self.assertEqual(run(self.config, edit=1, today=TODAY, out=io.StringIO()), 1)
        self.assertIn("'* 25:00 - Late' has no valid time. Nothing saved; your edit is kept in", error.getvalue())
        kept = Path(error.getvalue().rsplit(" ", 1)[1].strip())
        self.assertTrue(kept.exists())
        kept.unlink()
        self.assertEqual(len(self.stored()), 3)

        # One day: the message names it alone
        with patch.dict("os.environ", {"EDITOR": python_editor("pass")}):
            output = self.run_command(edit=1)
        self.assertTrue(output.endswith("✓ Logs updated for 2026-09-30\n"))
        self.assertEqual(len(self.stored()), 3)

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
        self.assertEqual(render_terminal([], color=False), "")
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

    def test_a_database_that_cannot_open_is_an_error(self) -> None:
        self.config.database_path = self.tmp
        with patch("sys.stderr", new=io.StringIO()) as error:
            self.assertEqual(run(self.config, out=io.StringIO()), 1)
        self.assertIn(f"Database Error: cannot open {self.tmp}", error.getvalue())


if __name__ == "__main__":
    unittest.main()
