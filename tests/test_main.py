import contextlib
import io
import unittest
from unittest.mock import patch

from fini.__main__ import main
from fini.app import FiniApp


class MainTest(unittest.TestCase):
    def test_version_prints_and_exits_and_no_argument_starts_the_tui(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            main(["--version"])
        self.assertEqual(raised.exception.code, 0)
        self.assertTrue(output.getvalue().startswith("fini "))

        with patch("fini.__main__.start") as start:
            main([])
        start.assert_called_once_with("fini", FiniApp)


if __name__ == "__main__":
    unittest.main()
