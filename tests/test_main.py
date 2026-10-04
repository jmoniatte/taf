import contextlib
import io
import unittest
from unittest.mock import patch

from travail.__main__ import main
from travail.app import TravailApp


class MainTest(unittest.TestCase):
    def test_version_prints_and_exits_and_no_argument_starts_the_tui(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertTrue(output.getvalue().startswith("travail "))

        with patch("travail.__main__.start") as start:
            main([])
        start.assert_called_once_with("travail", TravailApp)

    def test_log_runs_without_the_tui_and_takes_options_after_the_message(self) -> None:
        with (
            patch("travail.__main__.start") as start,
            patch("travail.__main__.load_config") as config,
            patch("travail.__main__.log_command.run", return_value=0) as run,
        ):
            for argv in (["log", "Did", "a", "thing", "@1h"], ["log", "-v", "2"], ["log", "-e"], ["log", "-e", "3"], ["log"], ["log", "x", "-v", "2"]):
                with self.assertRaises(SystemExit) as raised:
                    main(argv)
                self.assertEqual(raised.exception.code, 0)
        start.assert_not_called()
        self.assertEqual(
            [(call.args[1], call.kwargs) for call in run.call_args_list],
            [
                ("Did a thing @1h", {"view": None, "edit": None}),
                ("", {"view": 2, "edit": None}),
                ("", {"view": None, "edit": 1}),
                ("", {"view": None, "edit": 3}),
                ("", {"view": None, "edit": None}),
                ("x", {"view": 2, "edit": None}),
            ],
        )
        self.assertEqual(run.call_args.args[0], config.return_value)
        for argv in (["log", "-v", "0"], ["log", "-v", "2", "-e"]):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                main(argv)
            self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
