import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from taf.watch.view import Group, get_item, grouped, local, set_done, set_pinned, shown_items
from taf.database import open_database
from taf.watch.items import Item, save_item
from taf.watch.projects import add_project


def labels(rows: list) -> list[str]:
    return [row.name if isinstance(row, Group) else row.summary for row in rows]


class CurrentTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = open_database(Path(tmp.name) / "taf.sqlite3")
        self.addCleanup(self.db.close)

    def test_items_grouped_by_project_pinned_first(self) -> None:
        add_project(self.db, "follow")
        save_item(self.db, Item("slack", "C1:1", "action", "Answer Kevin", project="follow", url="https://slack/1",
                                happened_at="2026-10-06T16:00:00+00:00"))
        save_item(self.db, Item("slack", "C1:2", "question", "Ask about QA", project="follow", happened_at="2026-10-05T10:00:00+00:00"))
        save_item(self.db, Item("slack", "C2:1", "fyi", "Deploy moved", details="to Friday", happened_at="2026-10-02T10:00:00-07:00"))
        save_item(self.db, Item("github", "ci:u/1", "action", "CI fails on r#1", url="https://ci/1", happened_at="2026-10-01T10:00:00+00:00"))
        save_item(self.db, Item("github", "review:u/9", "action", "Review r#9", happened_at="2026-09-01T10:00:00+00:00"))

        items = shown_items(self.db, status="open")
        self.assertEqual(labels(grouped(items)), ["Pull Requests", "Review r#9", "follow", "Answer Kevin", "Ask about QA", "No project", "Deploy moved", "CI fails on r#1"])
        qa = next(item for item in items if item.summary == "Ask about QA")
        self.assertTrue(set_pinned(self.db, qa.id, True).pinned)
        self.assertEqual(labels(grouped(shown_items(self.db)))[3:5], ["Ask about QA", "Answer Kevin"])

        kevin = next(item for item in items if item.summary == "Answer Kevin")
        self.assertEqual(kevin.content, "Answer Kevin\n\n- Kind: action\n- Slack conversation: [https://slack/1](https://slack/1)")
        self.assertTrue(set_done(self.db, kevin.id, True).done)
        self.assertEqual([item.summary for item in shown_items(self.db, status="done")], ["Answer Kevin"])
        self.assertFalse(set_done(self.db, kevin.id, False).done)
        self.assertEqual([item.summary for item in shown_items(self.db, "friday")], ["Deploy moved"])
        self.assertIsNone(get_item(self.db, 999))
        # The PRs ready to deploy follow the reviews' count, and make the heading alone when there is none
        [heading] = [row for row in grouped(items, (3, "https://gh/q")) if isinstance(row, Group) and row.title]
        self.assertEqual((heading.name, heading.count, heading.note, heading.note_link), ("Pull Requests", 1, "3 PRs ready to deploy", "https://gh/q"))
        others = [item for item in items if not item.is_review]
        self.assertEqual(labels(grouped(others, (1, "u")))[0], "Pull Requests")
        self.assertEqual(grouped(others, (1, "u"))[0].note, "1 PR ready to deploy")
        self.assertNotEqual(labels(grouped(others, (0, "u")))[0], "Pull Requests")
        ci = next(item for item in items if item.source == "github")
        self.assertEqual((ci.source_name, ci.content), ("GitHub", "CI fails on r#1\n\n- Kind: action\n- Jenkins build: [https://ci/1](https://ci/1)\n- GitHub PR: [u/1](u/1)"))

    def test_times_are_local(self) -> None:
        self.assertEqual(local("2026-10-06T16:00:00+00:00"), datetime.fromisoformat("2026-10-06T16:00:00+00:00").astimezone().replace(tzinfo=None))
        self.assertEqual(local("2026-10-06 09:00:00"), datetime(2026, 10, 6, 9))
        self.assertIsNone(local(None))


if __name__ == "__main__":
    unittest.main()
