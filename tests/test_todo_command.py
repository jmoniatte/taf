import contextlib
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from taf.__main__ import main
from taf.config import Config
from taf.database import open_database
from taf.notes import TODO, create_note, set_pinned
from taf.todo_command import main as todo_main


class TodoCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config = Config(database_path=Path(tmp.name) / "taf.sqlite3")

    def run_todo(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err):
            code = todo_main(list(argv), self.config, out)
        return code, out.getvalue(), err.getvalue()

    def test_list_show_done_and_reopen(self) -> None:
        with contextlib.closing(open_database(self.config.database_path)) as database:
            renew = create_note(database, "Renew passport\n\n#home", TODO)
            create_note(database, "## Fix the docs #work", TODO)
            note = create_note(database, "Gate code")
            set_pinned(database, renew.id, True)
        run = self.run_todo

        # The last updated first; tags not in the summary after it, a star when pinned
        self.assertEqual(run("list"), (0, "#2 [ ] Fix the docs #work\n#1 [ ] Renew passport #home ★\n", ""))
        self.assertEqual(run(), run("list"))
        self.assertEqual(run("list", "#home")[1], "#1 [ ] Renew passport #home ★\n")
        self.assertEqual(run("show", "1")[1], "#1 [ ] Renew passport #home ★\n\nRenew passport\n\n#home\n")
        self.assertEqual(run("done", "1"), (0, "", ""))
        self.assertEqual(run("list")[1], "#2 [ ] Fix the docs #work\n")
        self.assertEqual(run("list", "--done")[1], "#1 [x] Renew passport #home ★\n")
        self.assertEqual(run("reopen", "1")[0], 0)
        self.assertEqual(len(run("list", "--all")[1].splitlines()), 2)
        # A note is not a todo
        self.assertEqual(run("done", str(note.id), "1"), (1, "", f"taf todo: no todo {note.id}\n"))

    def test_a_heading_loses_its_marks_and_a_longer_tag_does_not_hide_one(self) -> None:
        with contextlib.closing(open_database(self.config.database_path)) as database:
            create_note(database, "## Deploy #rails-api ##\n\n#rails", TODO)
        self.assertEqual(self.run_todo("list")[1], "#1 [ ] Deploy #rails-api #rails\n")

    def test_anything_else_writes_a_todo(self) -> None:
        code, out, _ = self.run_todo("Call", "the bank #money")
        self.assertEqual((code, out), (0, "Todo 1 created: Call the bank (#money)\n"))
        self.assertEqual(self.run_todo("list")[1], "#1 [ ] Call the bank #money\n")
        with contextlib.redirect_stdout(io.StringIO()) as help_text, self.assertRaises(SystemExit):
            todo_main(["--help"], self.config)
        self.assertIn("taf todo list|show|done|reopen", help_text.getvalue())
        self.assertIn('taf todo "Refactor', help_text.getvalue())

    def test_config_warnings_and_database_errors_are_one_line(self) -> None:
        self.config.warnings = ["stats_show: must be hours or percentages, using hours"]
        with patch("taf.todo_command.list_notes", side_effect=sqlite3.OperationalError("database is locked")):
            self.assertEqual(
                self.run_todo("list"), (1, "", "stats_show: must be hours or percentages, using hours\nDatabase Error: database is locked\n")
            )
        self.config.database_path = Path(self.config.database_path).parent
        code, _, err = self.run_todo("list")
        self.assertEqual(code, 1)
        self.assertIn("Database Error: cannot open", err)

    def test_taf_todo_and_todos_go_to_the_todo_command(self) -> None:
        with patch("taf.__main__.start") as start, patch("taf.__main__.todo_command.main", return_value=0) as command:
            for argv in (["todos"], ["todo", "done", "3"], ["todos", "Call", "the bank"]):
                with self.assertRaises(SystemExit):
                    main(argv)
                command.assert_called_with(argv[1:])
            with patch("taf.watch.cli.main", return_value=0) as watch, self.assertRaises(SystemExit):
                main(["watch", "done", "4"])
            watch.assert_called_once_with(["done", "4"])
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
