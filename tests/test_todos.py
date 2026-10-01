import sqlite3
import tempfile
import unittest
from pathlib import Path

from fini.database import open_database
from fini.todos import (
    create_todo,
    delete_todo,
    find_tags,
    get_todo,
    list_todos,
    set_done,
    set_pinned,
    split_query,
    split_status,
    tag_counts,
    tags_of,
    update_todo,
    without_tags,
)
from fini.widgets.todos_table import ListColors, summary_text


class TagsTest(unittest.TestCase):
    def test_yafyafs_rule_for_a_tag(self) -> None:
        self.assertEqual(tags_of("Call #Mom about #home-repairs, not a#tag nor `#code` nor #1st; #home again"), ["mom", "home-repairs", "home"])
        self.assertEqual(find_tags("x #work"), [(2, 7, "work")])
        self.assertEqual(split_query("passport #Home  renew #2"), (["passport", "renew", "#2"], ["home"]))


class TodosTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = open_database(Path(tmp.name) / "fini.sqlite3")
        self.addCleanup(self.db.close)

    def test_order_status_and_search(self) -> None:
        old = create_todo(self.db, "Renew passport #home")
        pinned = create_todo(self.db, "Review the PR #work")
        newest = create_todo(self.db, "Plan the 100% trip #home #travel")
        done = create_todo(self.db, "Pay taxes #home")
        set_pinned(self.db, pinned.id, True)
        set_done(self.db, done.id, True)
        for minute, todo in enumerate((pinned, done, old, newest)):
            self.db.execute("UPDATE todos SET updated_at = ? WHERE id = ?", (f"2026-09-30 10:0{minute}:00.000000", todo.id))
        ids = lambda todos: [todo.id for todo in todos]  # noqa: E731
        # The last updated first; pinned and done change nothing
        self.assertEqual(ids(list_todos(self.db)), [newest.id, old.id, pinned.id])
        self.assertEqual(ids(list_todos(self.db, status="done")), [done.id])
        self.assertEqual(ids(list_todos(self.db, status="all")), [newest.id, old.id, done.id, pinned.id])
        # Every word, any case, and every tag
        self.assertEqual(ids(list_todos(self.db, "RENEW pass", "all")), [old.id])
        self.assertEqual(ids(list_todos(self.db, "#home", "all")), [newest.id, old.id, done.id])
        self.assertEqual(ids(list_todos(self.db, "#home #travel", "all")), [newest.id])
        self.assertEqual(ids(list_todos(self.db, "100%", "all")), [newest.id])
        self.assertEqual(ids(list_todos(self.db, "1_0", "all")), [])
        # A word does not match a tag: "travel" is only a tag here, "home" only a tag, "trip" text
        self.assertEqual(ids(list_todos(self.db, "travel", "all")), [])
        self.assertEqual(ids(list_todos(self.db, "trip", "all")), [newest.id])
        self.assertEqual(ids(list_todos(self.db, "HOM", "all")), [])
        self.assertEqual(tag_counts(self.db), [("home", 3), ("travel", 1), ("work", 1)])

    def test_saving_rewrites_the_tags_done_keeps_its_first_time_and_delete_removes(self) -> None:
        todo = create_todo(self.db, "Renew passport #home")
        self.assertEqual((todo.tags, todo.pinned, todo.done), (("home",), False, False))
        todo = update_todo(self.db, todo.id, "Renew passport #travel\n\nbefore #June")
        self.assertEqual(todo.tags, ("travel", "june"))
        self.assertEqual(todo.summary, "Renew passport #travel")
        done = set_done(self.db, todo.id, True)
        self.assertTrue(done.done)
        self.db.execute("UPDATE todos SET done_at = '2026-01-01 08:00:00.000000'")
        self.assertEqual(f"{set_done(self.db, todo.id, True).done_at}", "2026-01-01 08:00:00")
        self.assertIsNone(set_done(self.db, todo.id, False).done_at)
        self.assertTrue(set_pinned(self.db, todo.id, True).pinned)
        # Stored as JSON, in the Ruby fini's timestamp format
        tags, created_at = sqlite3.connect(self.db.execute("PRAGMA database_list").fetchone()[2]).execute("SELECT tags, created_at FROM todos").fetchone()
        self.assertEqual(tags, '["travel", "june"]')
        self.assertRegex(created_at, r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.000000$")
        delete_todo(self.db, todo.id)
        self.assertIsNone(get_todo(self.db, todo.id))
        self.assertIsNone(update_todo(self.db, todo.id, "gone"))


if __name__ == "__main__":
    unittest.main()


class SummaryTextTest(unittest.TestCase):
    def test_inline_code_loses_its_backticks_and_keeps_tags_and_links_as_text(self) -> None:
        colors = ListColors(date="#111111", link="#0000ff", heading="#ffff00", tag="#ff00ff", code="#ff8800")
        text = summary_text("Fix `user.name` and `#nope https://x.io` for #work in [docs](https://d.io)", colors)
        self.assertEqual(text.plain, "Fix user.name and #nope https://x.io for #work in docs")
        styles = {text.plain[span.start : span.end]: str(span.style) for span in text.spans}
        self.assertEqual(styles["user.name"], "#ff8800")
        self.assertEqual(styles["#nope https://x.io"], "#ff8800")
        self.assertIn("#ff00ff", styles["#work"])
        self.assertIn("link https://d.io", styles["docs"])
        # A tag in code is not one: only #work carries a tag to click
        self.assertEqual([span.style.meta.get("tag") for span in text.spans if not isinstance(span.style, str) and span.style.meta.get("tag")], ["work"])

    def test_the_todos_other_tags_follow_the_text_in_cyan(self) -> None:
        colors = ListColors(tag="#ff00ff", heading="#ffff00", extra_tag="#00ffff")
        text = summary_text("Call the bank #money", colors, tags=("money", "home", "urgent"))
        self.assertEqual(text.plain, "Call the bank #money #home #urgent")
        styles = {text.plain[span.start : span.end]: span.style for span in text.spans}
        self.assertEqual((str(styles["#home"].color.name), styles["#home"].meta["tag"]), ("#00ffff", "home"))
        self.assertIn("#ff00ff", str(styles["#money"]))
        self.assertEqual(summary_text("No tags", colors).plain, "No tags")


class SearchWordsTest(unittest.TestCase):
    def test_a_word_matches_the_text_but_not_the_tags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = open_database(Path(tmp) / "fini.sqlite3")
            tagged = create_todo(db, "Fix the docs #api")
            text = create_todo(db, "Document the API")
            rapid = create_todo(db, "Rapid fix")
            code = create_todo(db, "Escape `#api` in markdown")
            ids = lambda todos: sorted(todo.id for todo in todos)  # noqa: E731
            self.assertEqual(ids(list_todos(db, "api")), ids([text, rapid, code]))
            self.assertEqual(ids(list_todos(db, "#api")), [tagged.id])
            self.assertEqual(ids(list_todos(db, "fix #api")), [tagged.id])
            self.assertEqual(without_tags("a #b c"), "a   c")
            db.close()

    def test_is_open_and_is_done_in_a_search(self) -> None:
        self.assertEqual(split_status("is:open fix #api"), ("open", "fix #api"))
        self.assertEqual(split_status("fix IS:Closed"), ("done", "fix"))
        self.assertEqual(split_status("is:done is:open x"), ("open", "x"))
        self.assertEqual(split_status("this:open"), ("all", "this:open"))
