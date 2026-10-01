import unittest

from fini.logs import format_duration


class FormatDurationTest(unittest.TestCase):
    def test_minutes_read_the_way_a_message_gives_them(self) -> None:
        self.assertEqual(
            [format_duration(minutes) for minutes in (None, 0, 15, 60, 105, 125, 600)],
            ["", "0m", "15m", "1h", "1h45", "2h05", "10h"],
        )


if __name__ == "__main__":
    unittest.main()
