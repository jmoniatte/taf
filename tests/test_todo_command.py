import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fini.__main__ import main
from fini.config import Config
from fini.database import open_database
from fini.todo_command import run, todo_content
from fini.todos import list_todos


class TodoContentTest(unittest.TestCase):
    def test_tags_at_the_end_go_on_their_own_line(self) -> None:
        self.assertEqual(todo_content("Refactor the entire subscription model #rails"), "Refactor the entire subscription model\n\n#rails")
        self.assertEqual(todo_content("  Ship it   #work #Urgent "), "Ship it\n\n#work #Urgent")
        # Inside the message, a tag stays put; with no text, or no tag, nothing moves
        self.assertEqual(todo_content("Ask #mom about it #home"), "Ask #mom about it\n\n#home")
        self.assertEqual(todo_content("Just text"), "Just text")
        self.assertEqual(todo_content("#only #tags"), "#only #tags")
        self.assertEqual(todo_content("Version #2"), "Version #2")


class TodoCommandTest(unittest.TestCase):
    def test_writes_the_todo_and_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(database_path=Path(tmp) / "fini.sqlite3")
            out = io.StringIO()
            self.assertEqual(run(config, "Refactor the subscription model #rails", out=out), 0)
            self.assertEqual(out.getvalue(), "Todo created: Refactor the subscription model (#rails)\n")
            database = open_database(config.database_path)
            [todo] = list_todos(database)
            database.close()
            self.assertEqual((todo.content, todo.tags), ("Refactor the subscription model\n\n#rails", ("rails",)))
            with contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(run(config, "  "), 2)
            self.assertIn("Nothing to save", error.getvalue())

    def test_main_runs_it_without_the_tui(self) -> None:
        with (
            patch("fini.__main__.start") as start,
            patch("fini.__main__.load_config") as config,
            patch("fini.__main__.todo_command.run", return_value=0) as command,
            self.assertRaises(SystemExit) as raised,
        ):
            main(["todo", "Call", "the bank #money"])
        self.assertEqual(raised.exception.code, 0)
        start.assert_not_called()
        command.assert_called_once_with(config.return_value, "Call the bank #money")
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(["todo"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
