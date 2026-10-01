import unittest
from datetime import date

from fini.stats import Entry, level, levels, minutes_by_action, minutes_by_month, periods

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


if __name__ == "__main__":
    unittest.main()
