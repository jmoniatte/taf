import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from taf.database import open_database
from taf.notes import (
    NOTE,
    TODO,
    Note,
    create_note,
    date_line,
    extra_tags,
    delete_note,
    find_tags,
    front_matter,
    get_note,
    heading_text,
    list_notes,
    long_date,
    set_done,
    set_pinned,
    split_query,
    split_status,
    tag_counts,
    tags_of,
    update_note,
    without_tags,
)
from taf.widgets.notes_table import ListColors, summary_text


class TagsTest(unittest.TestCase):
    def test_yafyafs_rule_for_a_tag(self) -> None:
        self.assertEqual(tags_of("Call #Mom about #home-repairs, not a#tag nor `#code` nor #1st; #home again"), ["mom", "home-repairs", "home"])
        self.assertEqual(find_tags("x #work"), [(2, 7, "work")])
        self.assertEqual(split_query("passport #Home  renew #2"), (["passport", "renew", "#2"], ["home"]))

    def test_extra_tags_are_those_not_in_the_summary_and_a_heading_loses_its_marks(self) -> None:
        created = datetime(2026, 9, 5, 9, 0)
        note = Note(1, TODO, "Deploy #rails-api\n\n#rails #work", ("rails-api", "rails", "work"), False, None, created, created)
        # #rails-api in the summary does not hide #rails
        self.assertEqual(extra_tags(note), ("rails", "work"))
        self.assertEqual(
            [heading_text(summary) for summary in ("## Fix the docs ##", "# Title #tag", "#tag not a heading", "Plain")],
            ["Fix the docs", "Title #tag", "#tag not a heading", "Plain"],
        )


class NotesTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = open_database(Path(tmp.name) / "taf.sqlite3")
        self.addCleanup(self.db.close)

    def test_order_status_and_search(self) -> None:
        old = create_note(self.db, "Renew passport #home", TODO)
        pinned = create_note(self.db, "Review the PR #work", TODO)
        newest = create_note(self.db, "Plan the 100% trip #home #travel", TODO)
        done = create_note(self.db, "Pay taxes #home", TODO)
        set_pinned(self.db, pinned.id, True)
        set_done(self.db, done.id, True)
        for minute, todo in enumerate((pinned, done, old, newest)):
            self.db.execute("UPDATE notes SET updated_at = ? WHERE id = ?", (f"2026-09-30 10:0{minute}:00.000000", todo.id))
        ids = lambda todos: [todo.id for todo in todos]  # noqa: E731
        # The last updated first; pinned and done change nothing
        self.assertEqual(ids(list_notes(self.db, TODO, status="open")), [newest.id, old.id, pinned.id])
        self.assertEqual(ids(list_notes(self.db, TODO, status="done")), [done.id])
        self.assertEqual(ids(list_notes(self.db, TODO, status="all")), [newest.id, old.id, done.id, pinned.id])
        # Every word, any case, and every tag
        self.assertEqual(ids(list_notes(self.db, TODO, "RENEW pass", "all")), [old.id])
        self.assertEqual(ids(list_notes(self.db, TODO, "#home", "all")), [newest.id, old.id, done.id])
        self.assertEqual(ids(list_notes(self.db, TODO, "#home #travel", "all")), [newest.id])
        self.assertEqual(ids(list_notes(self.db, TODO, "100%", "all")), [newest.id])
        self.assertEqual(ids(list_notes(self.db, TODO, "1_0", "all")), [])
        # A word does not match a tag: "travel" is only a tag here, "home" only a tag, "trip" text
        self.assertEqual(ids(list_notes(self.db, TODO, "travel", "all")), [])
        self.assertEqual(ids(list_notes(self.db, TODO, "trip", "all")), [newest.id])
        self.assertEqual(ids(list_notes(self.db, TODO, "HOM", "all")), [])
        self.assertEqual(tag_counts(self.db, TODO), [("home", 3), ("travel", 1), ("work", 1)])

    def test_saving_rewrites_the_tags_done_keeps_its_first_time_and_delete_removes(self) -> None:
        todo = create_note(self.db, "Renew passport #home", TODO)
        self.assertEqual((todo.tags, todo.pinned, todo.done), (("home",), False, False))
        todo = update_note(self.db, todo.id, "Renew passport #travel\n\nbefore #June")
        self.assertEqual(todo.tags, ("travel", "june"))
        self.assertEqual(todo.summary, "Renew passport #travel")
        done = set_done(self.db, todo.id, True)
        self.assertTrue(done.done)
        self.db.execute("UPDATE notes SET done_at = '2026-01-01 08:00:00.000000'")
        self.assertEqual(f"{set_done(self.db, todo.id, True).done_at}", "2026-01-01 08:00:00")
        self.assertIsNone(set_done(self.db, todo.id, False).done_at)
        self.assertTrue(set_pinned(self.db, todo.id, True).pinned)
        # Stored as JSON, in the Ruby fini's timestamp format
        tags, created_at = sqlite3.connect(self.db.execute("PRAGMA database_list").fetchone()[2]).execute("SELECT tags, created_at FROM notes").fetchone()
        self.assertEqual(tags, '["travel", "june"]')
        self.assertRegex(created_at, r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.000000$")
        delete_note(self.db, todo.id)
        self.assertIsNone(get_note(self.db, todo.id))
        self.assertIsNone(update_note(self.db, todo.id, "gone"))

    def test_notes_and_todos_are_kept_apart_and_a_note_is_never_done(self) -> None:
        todo = create_note(self.db, "Renew passport #home", TODO)
        note = create_note(self.db, "Passport number is in the safe #home #papers")
        self.assertEqual((note.kind, note.tags, note.is_todo), (NOTE, ("home", "papers"), False))
        ids = lambda notes: [shown.id for shown in notes]  # noqa: E731
        self.assertEqual(ids(list_notes(self.db, NOTE)), [note.id])
        self.assertEqual(ids(list_notes(self.db, TODO)), [todo.id])
        self.assertEqual(ids(list_notes(self.db, NOTE, "#home #papers")), [note.id])
        self.assertEqual(tag_counts(self.db, NOTE), [("home", 1), ("papers", 1)])
        self.assertEqual(tag_counts(self.db, TODO), [("home", 1)])
        self.assertIsNone(set_done(self.db, note.id, True).done_at)
        self.assertTrue(set_pinned(self.db, note.id, True).pinned)
        self.assertEqual(list(front_matter(note)), ["id", "created_at", "updated_at", "pinned"])
        self.assertEqual(list(front_matter(todo)), ["id", "created_at", "updated_at", "done_at", "pinned"])


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
            db = open_database(Path(tmp) / "taf.sqlite3")
            tagged = create_note(db, "Fix the docs #api", TODO)
            text = create_note(db, "Document the API", TODO)
            rapid = create_note(db, "Rapid fix", TODO)
            code = create_note(db, "Escape `#api` in markdown", TODO)
            ids = lambda todos: sorted(todo.id for todo in todos)  # noqa: E731
            self.assertEqual(ids(list_notes(db, TODO, "api")), ids([text, rapid, code]))
            self.assertEqual(ids(list_notes(db, TODO, "#api")), [tagged.id])
            self.assertEqual(ids(list_notes(db, TODO, "fix #api")), [tagged.id])
            self.assertEqual(without_tags("a #b c"), "a   c")
            db.close()

    def test_is_open_and_is_done_in_a_search(self) -> None:
        self.assertEqual(split_status("is:open fix #api"), ("open", "fix #api"))
        self.assertEqual(split_status("fix IS:Closed"), ("done", "fix"))
        self.assertEqual(split_status("is:done is:open x"), ("open", "x"))
        self.assertEqual(split_status("this:open"), ("all", "this:open"))

class DateTest(unittest.TestCase):
    def test_dates_have_a_time_and_say_created_or_updated(self) -> None:
        now = datetime(2026, 10, 7, 18, 0)
        self.assertEqual(long_date(datetime(2026, 10, 7, 15, 9), now), "Today at 3:09pm")
        self.assertEqual(long_date(datetime(2026, 10, 6, 0, 5), now), "Yesterday at 12:05am")
        self.assertEqual(long_date(datetime(2026, 10, 5, 12, 30), now), "October 5, 2026 at 12:30pm")
        created = datetime(2026, 9, 5, 9, 0)
        note = Note(1, TODO, "x", (), False, None, created, created)
        self.assertEqual(date_line(note), "Created September 5, 2026 at 9:00am")
        changed = Note(1, TODO, "x", (), False, None, created, datetime(2026, 9, 6, 10, 0))
        self.assertEqual(date_line(changed), "Updated September 6, 2026 at 10:00am")
        # What a table row and a detail view read, as from a watch item
        done = Note(7, TODO, "x", (), False, created, created, created)
        self.assertEqual((note.links, note.gray, done.gray, done.row_key, changed.date_text), ([], False, True, "7", date_line(changed)))
