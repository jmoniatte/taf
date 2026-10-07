import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from tui_kit.theme import load_palette

from taf.database import open_database
from taf.logs import create_log
from taf.message import Inference
from taf.stats import Entry, Period, level, levels, load_entries, minutes_by_action, minutes_by_month, periods, holidays_off, time_off_days
from taf.widgets.stats_view import CHART_HEIGHT, DAY, BrailleGrid, graph, month_chart

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

    def test_a_day_off_is_blue_and_a_us_holiday_red_in_the_graph(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            connection = open_database(Path(tmp) / "taf.sqlite3")
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
        # Labor Day, Monday, September 7, 2026, then Monday 14, an ordinary day; Labor Day 2025 had work
        holidays = holidays_off([Entry(date(2025, 9, 1), "code", 60)], date(2026, 10, 1))
        self.assertIn(date(2026, 9, 7), holidays)
        self.assertIn(date(2025, 12, 25), holidays)
        self.assertNotIn(date(2025, 9, 1), holidays)
        self.assertNotIn(date(2026, 9, 14), holidays)
        # Red even when logged as time off
        text = graph({}, [0, 0, 0], date(2026, 9, 7), date(2026, 9, 14), palette, date(2026, 10, 1), {date(2026, 9, 7)}, holidays)
        red = [text.plain[span.start : span.end] for span in text.spans if span.style == palette["red"]]
        self.assertEqual(red, [DAY, DAY])
        # Only the legend's square is blue
        self.assertEqual([span.style for span in text.spans].count(palette["blue"]), 1)
        self.assertIn("Holiday", text.plain)

    def test_the_actions_are_lines_of_braille_dots_on_one_scale(self) -> None:
        grid = BrailleGrid(2, 1)
        grid.line((0, 0), (3, 3), "red")
        # A diagonal through both cells: the first two dots in one, the last two in the other
        self.assertEqual(grid.row(0).plain, chr(0x2800 + 0x01 + 0x10) + chr(0x2800 + 0x04 + 0x80))
        entries = [
            Entry(date(2025, 11, 3), "code", 480),
            Entry(date(2025, 12, 1), "code", 240),
            Entry(date(2025, 12, 2), "meet", 240),
            *(Entry(date(2025, 12, 3), name, 6) for name in ("ops", "debug", "learn", "support", "admin")),
        ]
        palette = load_palette("onedark")
        colors = dict(zip(("code", "meet", "ops", "debug", "learn", "support", "admin"), ("blue", "purple", "yellow", "orange", "cyan", "red", "green")))
        period = Period("Last 12 months", date(2025, 10, 1), date(2026, 9, 30))
        lines = month_chart(entries, period, None, colors, palette, date(2026, 1, 15), percentages=True).plain.splitlines()
        # Code is all of November: the scale goes to 100%, from the first month with time to this one
        self.assertEqual(len(lines), CHART_HEIGHT + 4)
        self.assertTrue(lines[0].startswith("100% │"))
        self.assertTrue(lines[CHART_HEIGHT - 1].startswith("  0% │"))
        self.assertEqual(lines[CHART_HEIGHT + 1].split(), ["Nov", "2026"])
        # The first CHART_ACTIONS actions only
        self.assertEqual(lines[-1].split(), ["──", "code", "──", "meet", "──", "ops"])
        picked = month_chart(entries, period, "meet", colors, palette, date(2026, 1, 15), percentages=False).plain.splitlines()
        self.assertTrue(picked[0].startswith("10 h │"))
        self.assertEqual(picked[-1].split(), ["──", "meet"])

if __name__ == "__main__":
    unittest.main()
