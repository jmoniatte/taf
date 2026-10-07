import contextlib
import io
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
    def test_list_show_done_and_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(database_path=Path(tmp) / "taf.sqlite3")
            with contextlib.closing(open_database(config.database_path)) as database:
                renew = create_note(database, "Renew passport\n\n#home", TODO)
                create_note(database, "## Fix the docs #work", TODO)
                note = create_note(database, "Gate code")
                set_pinned(database, renew.id, True)

            def run(*argv: str) -> tuple[int, str, str]:
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stderr(err):
                    code = todo_main(config, list(argv), out)
                return code, out.getvalue(), err.getvalue()

            # The last updated first; tags not in the summary after it, a star when pinned
            self.assertEqual(run("list"), (0, "#2 [ ] Fix the docs #work\n#1 [ ] Renew passport #home ★\n", ""))
            self.assertEqual(run("list", "#home")[1], "#1 [ ] Renew passport #home ★\n")
            self.assertEqual(run("show", "1")[1], "#1 [ ] Renew passport #home ★\n\nRenew passport\n\n#home\n")
            self.assertEqual(run("done", "1"), (0, "", ""))
            self.assertEqual(run("list")[1], "#2 [ ] Fix the docs #work\n")
            self.assertEqual(run("list", "--done")[1], "#1 [x] Renew passport #home ★\n")
            self.assertEqual(run("reopen", "1")[0], 0)
            self.assertEqual(len(run("list", "--all")[1].splitlines()), 2)
            # A note is not a todo
            self.assertEqual(run("done", str(note.id), "1"), (1, "", f"taf todo: no todo {note.id}\n"))

    def test_taf_todo_routes_to_the_commands_or_writes_one(self) -> None:
        with (
            patch("taf.__main__.start") as start,
            patch("taf.__main__.load_config") as config,
            patch("taf.__main__.todo_command.main", return_value=0) as command,
            patch("taf.__main__.note_command.run", return_value=0) as write,
        ):
            for argv, called in ((["todos"], ["list"]), (["todo", "done", "3"], ["done", "3"]), (["todos", "list", "--all"], ["list", "--all"])):
                with self.assertRaises(SystemExit):
                    main(argv)
                command.assert_called_with(config.return_value, called)
            with self.assertRaises(SystemExit):
                main(["todos", "Call", "the bank"])
            write.assert_called_once_with(config.return_value, "Call the bank", "todo")
            with patch("taf.watch.cli.main", return_value=0) as watch, self.assertRaises(SystemExit):
                main(["watch", "done", "4"])
            watch.assert_called_once_with(["done", "4"])
        start.assert_not_called()


if __name__ == "__main__":
    unittest.main()
