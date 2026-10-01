import asyncio
import contextlib
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Input, Select, Static
from tui_kit.dialog import ConfirmDialog

from fini.app import FiniApp
from fini.config import Config
from fini.database import open_database
from fini.todos import create_todo, list_todos, long_date, set_done, set_pinned
from fini.widgets import TodoDetail, TodosTab, TodosTable


def python_editor(code: str) -> str:
    """An $EDITOR that runs Python on the file, whose path is sys.argv[1]."""
    return shlex.join([sys.executable, "-c", code])


def writes(content: str) -> str:
    return python_editor(f"import sys; open(sys.argv[1], 'w').write({content!r})")


@contextlib.contextmanager
def suspend(_app):
    # The headless test driver cannot suspend, and these editors do not need the terminal
    yield


class TodosViewTest(unittest.TestCase):
    def run_app(self, body, todos=()) -> None:
        async def main() -> None:
            with tempfile.TemporaryDirectory() as tmp, patch("fini.app.FiniApp.suspend", suspend):
                path = Path(tmp) / "fini.sqlite3"
                self.db = open_database(path)
                self.made = [create_todo(self.db, content) for content in todos]
                app = FiniApp(Config(theme="onedark", database_path=path))
                async with app.run_test(size=(110, 24)) as pilot:
                    await pilot.pause()
                    await body(app, pilot)
                self.db.close()

        asyncio.run(main())

    def rows(self, app) -> list[list[str]]:
        table = app.query_one(TodosTable)
        return [[str(cell) for cell in table.get_row_at(row)] for row in range(table.row_count)]

    def summaries(self, app) -> list[str]:
        return [row[1] for row in self.rows(app)]

    def status(self, app) -> str:
        return str(app.query_one("#todos-status", Static).render())

    def test_the_list_and_its_keys(self) -> None:
        async def body(app, pilot) -> None:
            renew, review, plan = self.made
            for minute, todo in enumerate((renew, review, plan)):
                self.db.execute("UPDATE todos SET updated_at = ? WHERE id = ?", (f"2026-09-30 10:0{minute}:00.000000", todo.id))
            set_pinned(self.db, renew.id, True)
            await pilot.press("r")
            await pilot.pause()
            # The last updated first; pinned or not
            self.assertEqual(self.summaries(app), ["Plan the trip", "Review the PR #work", "Renew passport #home"])
            self.assertEqual([row[0] for row in self.rows(app)], ["\U000f0131  ☆", "\U000f0131  ☆", "\U000f0131  ★"])
            self.assertEqual(self.status(app), "3 open todos")
            self.assertTrue(app.query_one(TodosTable).has_focus)

            # x marks the highlighted one done in its row: it leaves the open list on the next load
            await pilot.press("j", "x")
            await pilot.pause()
            self.assertEqual(self.summaries(app), ["Plan the trip", "Review the PR #work", "Renew passport #home"])
            self.assertEqual(self.rows(app)[1][0], "\U000f0132  ☆")
            await pilot.press("r")
            await pilot.pause()
            self.assertEqual(self.summaries(app), ["Plan the trip", "Renew passport #home"])
            # f shows the done ones, then all, still by when they were updated
            await pilot.press("f")
            await pilot.pause()
            self.assertEqual((self.summaries(app), self.status(app)), (["Review the PR #work"], "1 done todo"))
            await pilot.press("f")
            await pilot.pause()
            self.assertEqual(self.status(app), "3 todos")
            self.assertEqual(self.summaries(app), ["Plan the trip", "Review the PR #work", "Renew passport #home"])
            # p pins the highlighted one in its row, and space unpins it; the order never changes
            await pilot.press("k", "k", "p")
            await pilot.pause()
            self.assertEqual(self.rows(app)[0][0], "\U000f0131  ★")
            await pilot.press("space", "r")
            await pilot.pause()
            self.assertEqual(self.rows(app)[0][0], "\U000f0131  ☆")
            self.assertEqual(self.summaries(app), ["Plan the trip", "Review the PR #work", "Renew passport #home"])
            self.assertEqual(app.query_one(TodosTable).cursor_row, 0)

            # / searches, Enter runs it and goes back to the list
            await pilot.press("slash")
            self.assertTrue(app.query_one("#search", Input).has_focus)
            await pilot.press(*"PASS", "enter")
            await pilot.pause()
            self.assertEqual((self.summaries(app), self.status(app)), (["Renew passport #home"], "1 todo matching 'PASS'"))
            self.assertTrue(app.query_one(TodosTable).has_focus)

            # The Tags dropdown lists the tags with counts; picking one adds it to the search
            tags = app.query_one("#tag-selector", Select)
            # No "Tags" placeholder in the list: Any stands for no tag
            self.assertEqual([str(prompt) for prompt, _ in tags._options], ["Any tag", "home (1)", "work (1)"])
            self.assertEqual(tags.value, "any tag")
            app.query_one("#search", Input).value = ""
            tags.value = "work"
            await pilot.pause()
            self.assertEqual((app.query_one("#search", Input).value, self.summaries(app)), ("#work", ["Review the PR #work"]))
            # It shows the search's tag, as the status dropdown shows its status
            self.assertEqual(tags.value, "work")
            # Another tag takes the place of the one in the search; its words stay
            app.query_one("#search", Input).value = "renew #work"
            tags.value = "home"
            await pilot.pause()
            self.assertEqual((app.query_one("#search", Input).value, self.summaries(app)), ("renew #home", ["Renew passport #home"]))
            # Any takes the tag out, as All does the status
            app.query_one("#search", Input).value = "is:open renew #home"
            tags.value = "any tag"
            await pilot.pause()
            self.assertEqual((app.query_one("#search", Input).value, self.summaries(app)), ("is:open renew", ["Renew passport #home"]))
            self.assertEqual(tags.value, "any tag")
            # A tag typed in the search shows there too; one no todo has shows as Any, and stays in the search
            for typed, shown in (("#home", "home"), ("#ghost", "any tag")):
                await pilot.press("slash")
                app.query_one("#search", Input).value = typed
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual((tags.value, app.query_one("#search", Input).value), (shown, typed))

        self.run_app(body, todos=("Renew passport #home", "Review the PR #work", "Plan the trip"))

    def test_the_status_lives_in_the_search_as_is_open_or_is_done(self) -> None:
        async def body(app, pilot) -> None:
            search = app.query_one("#search", Input)
            status = app.query_one("#todo-status", Select)
            set_done(self.db, self.made[0].id, True)
            await pilot.press("r")
            await pilot.pause()
            # Open by default, and the search says so
            self.assertEqual((search.value, status.value, self.summaries(app)), ("is:open", "open", ["Ship the API"]))
            # The dropdown, or f, puts its status first in the search in place of the other; All takes it out
            search.value = "is:open #work"
            status.value = "done"
            await pilot.pause()
            self.assertEqual((search.value, self.summaries(app), self.status(app)), ("is:done #work", ["Fix the docs #work"], "1 done todo matching '#work'"))
            await pilot.press("f")
            await pilot.pause()
            self.assertEqual((search.value, status.value), ("#work", "all"))
            await pilot.press("f")
            await pilot.pause()
            self.assertEqual(search.value, "is:open #work")
            # Typed in the search, it sets the dropdown; is:closed means done, as on GitHub, and no is: means all
            for typed, expected in (("is:closed docs", "done"), ("api", "all"), ("IS:OPEN", "open")):
                await pilot.press("slash")
                search.value = typed
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual(status.value, expected)
            self.assertEqual(self.summaries(app), ["Ship the API"])

        self.run_app(body, todos=("Fix the docs #work", "Ship the API"))

    def test_the_refresh_button_reloads_the_list_and_shows_only_there(self) -> None:
        async def body(app, pilot) -> None:
            refresh = app.query_one("#btn-refresh")
            self.assertTrue(refresh.display)
            self.assertTrue(refresh.has_class("tinted", "-green"))
            # Written elsewhere, say by fini todo, it shows once refreshed
            create_todo(self.db, "Written from the shell")
            self.assertEqual(self.summaries(app), ["Old one"])
            await pilot.click("#btn-refresh")
            await pilot.pause()
            self.assertEqual(self.summaries(app), ["Written from the shell", "Old one"])
            self.assertTrue(app.query_one(TodosTable).has_focus)
            # Not on a todo, nor on Logs
            await pilot.press("enter")
            await pilot.pause()
            self.assertFalse(refresh.display)
            await pilot.press("escape")
            await pilot.pause()
            self.assertTrue(refresh.display)
            await pilot.press("tab")
            await pilot.pause()
            self.assertFalse(refresh.display)

        self.run_app(body, todos=("Old one",))

    def test_clicks_on_the_box_the_star_and_a_tag(self) -> None:
        async def body(app, pilot) -> None:
            table = app.query_one(TodosTable)
            # The box's half of the first column, then the star's
            await pilot.click(table, offset=(1, 0))
            await pilot.pause()
            self.assertEqual(self.rows(app)[0][0], "\U000f0132  ☆")
            await pilot.click(table, offset=(4, 0))
            await pilot.pause()
            [todo] = list_todos(self.db, status="all")
            self.assertEqual((todo.done, todo.pinned), (True, True))
            # A tag filters on it
            await pilot.click(table, offset=(10, 0))
            await pilot.pause()
            self.assertEqual(app.query_one("#search", Input).value, "is:open #home")

        self.run_app(body, todos=("#home chores",))

    def test_new_edit_and_delete_go_through_the_editor(self) -> None:
        async def body(app, pilot) -> None:
            seen = Path(tempfile.gettempdir()) / f"fini-test-seen-{id(self)}"
            self.addCleanup(seen.unlink, missing_ok=True)
            code = f"import sys, shutil; shutil.copy(sys.argv[1], {str(seen)!r}); open(sys.argv[1], 'w').write('Buy milk #home')"
            with patch.dict("os.environ", {"EDITOR": python_editor(code)}):
                await pilot.press("n")
                await pilot.pause()
            # No front matter for a new todo
            self.assertEqual(seen.read_text(), "")
            self.assertEqual(self.summaries(app), ["Buy milk #home", "Old one"])
            # Shift+Enter edits the highlighted one; the editor got the content as it is
            # The front matter is dropped, changed or not
            code = (
                f"import sys, shutil; shutil.copy(sys.argv[1], {str(seen)!r}); "
                "open(sys.argv[1], 'w').write('---\\nadded: 1999-01-01\\n---\\n\\nBuy oat milk #home #shop\\n')"
            )
            with patch.dict("os.environ", {"EDITOR": python_editor(code)}):
                await pilot.press("shift+enter")
                await pilot.pause()
            todo = list_todos(self.db)[0]
            self.assertEqual(
                seen.read_text(),
                f"---\ncreated_at : {todo.created_at:%Y-%m-%d %H:%M}\nupdated_at : {todo.updated_at:%Y-%m-%d %H:%M}\n"
                "done_at    :\npinned     : false\n---\n\nBuy milk #home",
            )
            self.assertEqual(self.summaries(app), ["Buy oat milk #home #shop", "Old one"])
            self.assertEqual(list_todos(self.db)[0].tags, ("home", "shop"))

            # Pinned and done show too
            todo = list_todos(self.db)[0]
            set_pinned(self.db, todo.id, True)
            done = set_done(self.db, todo.id, True)
            with patch.dict("os.environ", {"EDITOR": python_editor(f"import sys, shutil; shutil.copy(sys.argv[1], {str(seen)!r})")}):
                await pilot.press("f", "f", "e")
                await pilot.pause()
            self.assertIn(f"done_at    : {done.done_at:%Y-%m-%d %H:%M}\npinned     : true\n---", seen.read_text())
            set_done(self.db, todo.id, False)
            set_pinned(self.db, todo.id, False)
            await pilot.press("f")
            await pilot.pause()

            # An editor that fails saves nothing, and says why
            with patch.dict("os.environ", {"EDITOR": python_editor("raise SystemExit(1)")}):
                await pilot.press("e")
                await pilot.pause()
            self.assertEqual(self.summaries(app), ["Buy oat milk #home #shop", "Old one"])
            # A new todo left empty is a cancel; an emptied one asks first
            with patch.dict("os.environ", {"EDITOR": writes("\n")}):
                await pilot.press("n")
                await pilot.pause()
                self.assertEqual(len(self.summaries(app)), 2)
                await pilot.press("e")
                await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmDialog)
            await pilot.press("enter")  # Cancel has focus
            await pilot.pause()
            self.assertEqual(len(self.summaries(app)), 2)
            with patch.dict("os.environ", {"EDITOR": writes("")}):
                await pilot.press("e")
                await pilot.pause()
            await pilot.click("#confirm-btn")
            await pilot.pause()
            self.assertEqual(self.summaries(app), ["Old one"])

        self.run_app(body, todos=("Old one",))

    def test_enter_shows_the_todo_and_editing_returns_where_it_started(self) -> None:
        async def body(app, pilot) -> None:
            tab = app.query_one(TodosTab)
            detail = app.query_one(TodoDetail)
            await pilot.press("enter")
            await pilot.pause()
            # Close, then the blue Edit, at the left of the footer
            close_button = app.query_one("#btn-close-todo")
            edit_button = app.query_one("#btn-edit")
            self.assertTrue(close_button.display and edit_button.display)
            self.assertEqual(close_button.region.y, edit_button.region.y)
            self.assertLess(close_button.region.right, edit_button.region.x)
            self.assertTrue(edit_button.has_class("tinted"))
            todo = list_todos(self.db)[0]
            self.assertTrue(detail.display)
            self.assertFalse(app.query_one("#todos-list").display)
            self.assertTrue(edit_button.display)
            # The star, outlined, then when it was last updated
            star = app.query_one("#todo-detail-pin", Static)
            date = app.query_one("#todo-detail-date", Static)
            self.assertEqual(str(star.render()).strip(), "☆")
            self.assertEqual(str(date.render()), f"Updated {long_date(todo.updated_at)}")
            # A click on the star pins, there and in the list, and leaves "Updated" as it was
            await pilot.click(star)
            await pilot.pause()
            self.assertEqual((str(star.render()).strip(), star.has_class("-pinned")), ("★", True))
            self.assertTrue(list_todos(self.db)[0].pinned)
            self.assertEqual(self.rows(app)[0][0], "\U000f0131  ★")
            self.assertEqual(str(date.render()), f"Updated {long_date(todo.updated_at)}")
            await pilot.click(star)
            await pilot.pause()
            self.assertEqual((str(star.render()).strip(), list_todos(self.db)[0].pinned), ("☆", False))
            # The box marks done and back, there and in the list, the date still "Updated"
            box = app.query_one("#todo-detail-done", Static)
            self.assertEqual(str(box.render()).strip(), "\U000f0131")
            await pilot.click(box)
            await pilot.pause()
            self.assertEqual(str(box.render()).strip(), "\U000f0132")
            self.assertTrue(list_todos(self.db, status="done"))
            self.assertEqual(self.rows(app)[0][0], "\U000f0132  ☆")
            self.assertEqual(str(date.render()), f"Updated {long_date(todo.updated_at)}")
            await pilot.click(box)
            await pilot.pause()
            self.assertEqual(str(box.render()).strip(), "\U000f0131")
            self.assertFalse(list_todos(self.db, status="done"))
            markdown = app.query_one("#todo-detail-markdown")
            self.assertIn("uv run fini", markdown.source)
            self.assertTrue(markdown.query("MarkdownFence"))

            # e edits, and saving comes back to the todo, its new content shown
            with patch.dict("os.environ", {"EDITOR": writes("# Ship it\n\n```\ncode\n```\n")}):
                await pilot.press("e")
                await pilot.pause()
            self.assertEqual(tab.viewing.id, todo.id)
            self.assertTrue(detail.display)
            self.assertEqual(markdown.source, "# Ship it\n\n```\ncode\n```")
            # So does the Edit button
            with patch.dict("os.environ", {"EDITOR": writes("Shipped")}):
                await pilot.click("#btn-edit")
                await pilot.pause()
            self.assertEqual(markdown.source, "Shipped")

            # Another tab hides Close and Edit; back, the todo shows with them
            await pilot.press("tab")
            await pilot.pause()
            self.assertFalse(close_button.display or edit_button.display)
            await pilot.press("tab")
            await pilot.pause()
            self.assertTrue(detail.display and close_button.display and edit_button.display)

            # Close goes back to the list, as does Escape, and both buttons leave
            await pilot.click("#btn-close-todo")
            await pilot.pause()
            self.assertFalse(detail.display or close_button.display or edit_button.display)
            await pilot.press("enter")
            await pilot.pause()
            self.assertTrue(detail.display)
            await pilot.press("escape")
            await pilot.pause()
            self.assertFalse(detail.display or close_button.display)
            self.assertTrue(app.query_one(TodosTable).has_focus)
            self.assertEqual(self.summaries(app), ["Shipped"])

            # Shift+Enter edits from the list, and saving stays on the list
            with patch.dict("os.environ", {"EDITOR": writes("Shipped twice")}):
                await pilot.press("shift+enter")
                await pilot.pause()
            self.assertFalse(detail.display)
            self.assertEqual(self.summaries(app), ["Shipped twice"])

            # The red Delete, after Edit, asks first; Cancel keeps the todo on show
            await pilot.press("enter")
            await pilot.pause()
            delete_button = app.query_one("#btn-delete")
            self.assertTrue(delete_button.display and delete_button.has_class("tinted", "-red"))
            self.assertLess(edit_button.region.right, delete_button.region.x)
            await pilot.click("#btn-delete")
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmDialog)
            await pilot.press("enter")  # Cancel has focus
            await pilot.pause()
            self.assertTrue(detail.display)
            # Confirmed, it is gone and the list is back, without Delete
            await pilot.click("#btn-delete")
            await pilot.pause()
            await pilot.click("#confirm-btn")
            await pilot.pause()
            self.assertFalse(detail.display or delete_button.display)
            self.assertEqual(self.summaries(app), [])
            self.assertEqual(list_todos(self.db, status="all"), [])

        self.run_app(body, todos=("# Release #work\n\n```bash\nuv run fini\n```",))

    def test_done_todos_are_gray_and_the_colors_follow_the_theme(self) -> None:
        async def body(app, pilot) -> None:
            set_done(self.db, self.made[0].id, True)
            await pilot.press("f", "r")
            await pilot.pause()
            app.apply_theme("dracula")
            await pilot.pause()
            summary = app.query_one(TodosTable).get_row_at(0)[1]
            self.assertIn("#6272a4", str(summary.spans[-1].style).lower())

        self.run_app(body, todos=("Done one #home",))


if __name__ == "__main__":
    unittest.main()
