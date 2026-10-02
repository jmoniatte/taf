import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from tui_kit.theme import load_palette

from fini.database import open_database
from fini.logs import create_log
from fini.message import Inference
from fini.stats import Entry, level, levels, load_entries, minutes_by_action, minutes_by_month, periods, time_off_days
from fini.widgets.stats_view import DAY, graph

ENTRIES = [
    Entry(date(2024, 12, 23), "code", 60),
    Entry(date(2025, 3, 3), "meet", 30),
    Entry(date(2025, 3, 20), "code", 90),
    Entry(date(2026, 9, 30), "code", 15),
]


class StatsTest(unittest.TestCase):
    def test_periods_start_no_earlier_than_the_first_log(self) -> None:
        found = [(period.label, period.first, period.last) for period in periods(ENTRIES, date(2026, 9, 30))]
        self.assertEqual(
            found,
            [
                ("Last 12 months", date(2025, 10, 1), date(2026, 9, 30)),
                ("2026", date(2026, 1, 1), date(2026, 12, 31)),
                ("2025", date(2025, 1, 1), date(2025, 12, 31)),
                ("2024", date(2024, 12, 23), date(2024, 12, 31)),
                ("All time", date(2024, 12, 23), date(2026, 12, 31)),
            ],
        )
        self.assertEqual([period.label for period in periods([], date(2026, 9, 30))], ["Last 12 months"])

    def test_minutes_add_up_per_action_and_per_month(self) -> None:
        self.assertEqual(minutes_by_action(ENTRIES), [("code", 165), ("meet", 30)])
        self.assertEqual(
            minutes_by_month(ENTRIES),
            [(date(2024, 12, 1), {"code": 60}), (date(2025, 3, 1), {"meet": 30, "code": 90}), (date(2026, 9, 1), {"code": 15})],
        )

    def test_a_day_shades_by_the_quartiles_of_the_days_with_logs(self) -> None:
        thresholds = levels([0, 60, 120, 180, 240])
        self.assertEqual(thresholds, [120, 180, 240])
        self.assertEqual([level(minutes, thresholds) for minutes in (0, 30, 120, 200, 600)], [0, 1, 2, 3, 4])
        self.assertEqual(levels([0]), [0, 0, 0])

    def test_a_day_of_time_off_only_is_blue_in_the_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            connection = open_database(Path(tmp) / "fini.sqlite3")
            self.addCleanup(connection.close)
            pto = Inference("code", [("pto", [])])
            # Monday: time off only, even without a duration; Tuesday: time off and work
            for when, message in (
                (datetime(2026, 9, 28, 9), "PTO @8h +pto"),
                (datetime(2026, 9, 29, 9), "AFK +pto"),
                (datetime(2026, 9, 29, 14), "Coded @2h"),
                (datetime(2026, 9, 30, 9), "Doctor +pto"),
            ):
                create_log(connection, message, pto, logged_at=when)
            entries = load_entries(connection)
            self.assertEqual([entry.action for entry in entries], ["code"])
            self.assertEqual(time_off_days(connection, entries), {date(2026, 9, 28), date(2026, 9, 30)})
        palette = load_palette("onedark")
        text = graph({date(2026, 9, 29): 120}, [0, 0, 0], date(2026, 9, 28), date(2026, 10, 1), palette, date(2026, 10, 1), {date(2026, 9, 28)})
        blue = [text.plain[span.start : span.end] for span in text.spans if span.style == palette["blue"]]
        # Monday, then the legend's square
        self.assertEqual(blue, [DAY, DAY])
        self.assertIn("Time off", text.plain)


if __name__ == "__main__":
    unittest.main()
