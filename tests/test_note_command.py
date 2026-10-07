import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from taf.__main__ import main
from taf.config import Config
from taf.database import open_database
from taf.note_command import note_content, run
from taf.notes import NOTE, TODO, list_notes


class NoteContentTest(unittest.TestCase):
    def test_tags_at_the_end_go_on_their_own_line(self) -> None:
        self.assertEqual(note_content("Refactor the entire subscription model #rails"), "Refactor the entire subscription model\n\n#rails")
        self.assertEqual(note_content("  Ship it   #work #Urgent "), "Ship it\n\n#work #Urgent")
        # Inside the message, a tag stays put; with no text, or no tag, nothing moves
        self.assertEqual(note_content("Ask #mom about it #home"), "Ask #mom about it\n\n#home")
        self.assertEqual(note_content("Just text"), "Just text")
        self.assertEqual(note_content("#only #tags"), "#only #tags")
        self.assertEqual(note_content("Version #2"), "Version #2")


class NoteCommandTest(unittest.TestCase):
    def test_writes_the_todo_or_note_and_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Config(database_path=Path(tmp) / "taf.sqlite3")
            out = io.StringIO()
            self.assertEqual(run(config, "Refactor the subscription model #rails", TODO, out=out), 0)
            self.assertEqual(out.getvalue(), "Todo 1 created: Refactor the subscription model (#rails)\n")
            database = open_database(config.database_path)
            [todo] = list_notes(database, TODO)
            self.assertEqual((todo.content, todo.tags), ("Refactor the subscription model\n\n#rails", ("rails",)))
            # A note by default
            out = io.StringIO()
            self.assertEqual(run(config, "Wifi password is on the fridge #home #wifi", out=out), 0)
            self.assertEqual(out.getvalue(), "Note 2 created: Wifi password is on the fridge (#home #wifi)\n")
            [note] = list_notes(database, NOTE)
            database.close()
            self.assertEqual(note.tags, ("home", "wifi"))
            with contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(run(config, "  "), 2)
            self.assertIn("Nothing to save", error.getvalue())

    def test_main_runs_it_without_the_tui(self) -> None:
        with (
            patch("taf.__main__.start") as start,
            patch("taf.__main__.load_config") as config,
            patch("taf.__main__.note_command.run", return_value=0) as command,
        ):
            for kind in ("todo", "note"):
                with self.assertRaises(SystemExit) as raised:
                    main([kind, "Call", "the bank #money"])
                self.assertEqual(raised.exception.code, 0)
                command.assert_called_with(config.return_value, "Call the bank #money", kind)
        start.assert_not_called()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(["note"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
