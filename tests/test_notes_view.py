import asyncio
import contextlib
import shlex
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Input, Select, Static
from tui_kit.dialog import ConfirmDialog

from taf.app import TafApp
from taf.config import Config
from taf.database import open_database
from taf.notes import NOTE, TODO, create_note, list_notes, long_date, set_done, set_pinned
from taf.watch.items import Item, get_item, now, record_run, save_item
from taf.watch.projects import add_project
from taf.widgets import WatchTab, WatchDetail, NoteDetail, NotesTab, NotesTable, TodoDetail, TodosTab


def python_editor(code: str) -> str:
    """An $EDITOR that runs Python on the file, whose path is sys.argv[1]."""
    return shlex.join([sys.executable, "-c", code])


def writes(content: str) -> str:
    return python_editor(f"import sys; open(sys.argv[1], 'w').write({content!r})")


@contextlib.contextmanager
def suspend(_app):
    # The headless test driver cannot suspend, and these editors do not need the terminal
    yield


class AppCase(unittest.TestCase):
    # The tab the test starts on, which the app opens on or tab moves to
    TAB = "notes"

    def run_app(self, body, todos=(), notes=()) -> None:
        async def main() -> None:
            with tempfile.TemporaryDirectory() as tmp, patch("taf.app.TafApp.suspend", suspend):
                path = Path(tmp) / "taf.sqlite3"
                self.db = open_database(path)
                self.made = [create_note(self.db, content, TODO) for content in todos]
                for content in notes:
                    create_note(self.db, content)
                app = TafApp(Config(theme="onedark", database_path=path, path=Path(tmp) / "config.yml"))
                async with app.run_test(size=(110, 24)) as pilot:
                    await pilot.pause()
                    while app.tab != self.TAB:
                        await pilot.press("tab")
                        await pilot.pause()
                    await body(app, pilot)
                self.db.close()

        asyncio.run(main())

    def rows(self, app) -> list[list[str]]:
        table = app.query_one("#todos-view").query_one(NotesTable)
        # Each cell carries its own padding
        return [[str(cell).strip() for cell in table.get_row_at(row)] for row in range(table.row_count)]

    def summaries(self, app) -> list[str]:
        return [row[-1] for row in self.rows(app)]

    def status(self, app) -> str:
        return str(app.query_one("#todos-view").query_one("#notes-status", Static).render())



class WatchTabTest(AppCase):
    TAB = "watch"

    def test_shown_items_under_their_project_to_close_and_star(self) -> None:
        async def body(app, pilot) -> None:
            add_project(self.db, "follow")
            save_item(self.db, Item("slack", "C1:1", "action", "Answer Kevin", project="follow", url="https://slack/1",
                                    happened_at="2026-10-06T16:00:00+00:00"))
            save_item(self.db, Item("github", "ci:u/1", "action", "CI fails on r#1", url="https://ci/1", happened_at="2026-01-01T10:00:00+00:00"))
            tab = app.query_one("#watch-view", WatchTab)
            await pilot.press("r")
            await pilot.pause()
            table = tab.query_one(NotesTable)
            lines = ["".join(str(cell) for cell in table.get_row_at(row)).rstrip() for row in range(table.row_count)]
            # A heading per project from the left edge, a blank row between them; no id for an item
            self.assertEqual(lines, [
                " follow (1)", "    \U000f0131  ☆  Answer Kevin  \U000f04b1", "", " No project (1)", "    \U000f0131  ☆  CI fails on r#1  \uf2ec  \U000f02a4",
            ])
            self.assertEqual(str(tab.query_one("#notes-status", Static).render()), "2 open items")
            # The cursor starts on an item, never a heading; j skips the blank row and the heading
            self.assertEqual(table.cursor_row, 1)
            await pilot.press("j")
            self.assertEqual(table.cursor_row, 4)
            await pilot.press("k", "x", "p")
            await pilot.pause()
            kevin = get_item(self.db, 1)
            self.assertEqual((kevin["status"], kevin["pinned"]), ("done", 1))
            # Each icon links to its own page, a click opening it: failing CI's build in red, its PR in blue
            links = [[(span.style.link, span.style.color.name) for span in table.get_row_at(row)[2].spans if span.style.link]
                     for row in (1, 4)]
            palette = app.palette
            self.assertEqual(links, [[("https://slack/1", palette["blue"])], [("https://ci/1", palette["red"]), ("u/1", palette["blue"])]])
            # Done ones leave the open list on the next load; f shows them
            await pilot.press("r")
            await pilot.pause()
            self.assertEqual(str(tab.query_one("#notes-status", Static).render()), "1 open item")
            await pilot.press("f")
            await pilot.pause()
            self.assertEqual(str(tab.query_one("#notes-status", Static).render()), "1 done item")

            # Enter shows it in full, without Edit or Delete; its box closes it again
            await pilot.press("enter")
            await pilot.pause()
            detail = tab.query_one(WatchDetail)
            self.assertTrue(detail.display)
            self.assertEqual(str(detail.query_one("#note-detail-id", Static).render()), "Slack")
            self.assertFalse(detail.query_one("#btn-edit").display or detail.query_one("#btn-delete").display)
            await pilot.click("#watch-view #note-detail-done")
            await pilot.pause()
            self.assertEqual(get_item(self.db, 1)["status"], "open")
            await pilot.press("escape")
            await pilot.pause()
            self.assertFalse(detail.display)

        self.run_app(body)

    def test_the_pull_requests_heading_links_to_those_ready_to_deploy(self) -> None:
        async def body(app, pilot) -> None:
            save_item(self.db, Item("github", "review:u/9", "action", "Review r#9", url="u/9"))
            view = app.query_one("#watch-view").list
            # As GitHub answered: the tab asks it in a thread, only with deploy_repo in the config
            view._ready_known((8, "https://gh/ready"))
            await pilot.pause()
            table = view.table
            heading = "".join(str(cell) for cell in table.get_row_at(0))
            self.assertEqual(heading.rstrip(), " Pull Requests (1) - 8 PRs ready to deploy")
            x = heading.index("8 PRs")
            with patch.object(app, "open_url") as opened:
                await pilot.click("#watch-view #notes-table", offset=(x, 0))
                await pilot.pause()
            opened.assert_called_once_with("https://gh/ready")
            self.assertEqual(table.cursor_row, 1)

        self.run_app(body)

    def test_collect_runs_taf_watch_collect_in_the_background(self) -> None:
        def fake_popen(code: int, out: str, err: str):
            """A collect that is over at once, having printed out and err into the files it was given."""
            started = []

            def popen(command, stdout, stderr, **kwargs):
                started.append((command, kwargs))
                stdout.write(out)
                stderr.write(err)
                return unittest.mock.Mock(poll=lambda: code)

            popen.started = started
            return popen

        async def body(app, pilot) -> None:
            button = app.query_one("#btn-collect")
            self.assertTrue(button.display)
            popen = fake_popen(0, "github: 3 open PRs, 1 new items\nslack: 2 items", "")
            with patch("taf.widgets.watch_tab.subprocess.Popen", popen):
                await pilot.click("#btn-collect")
                await app.workers.wait_for_complete()
                await pilot.pause()
            [(command, kwargs)] = popen.started
            # Apart from taf: its own session, so quitting taf does not stop it
            self.assertEqual((command[1:], kwargs["start_new_session"]), (["-m", "taf", "watch", "collect"], True))
            self.assertEqual((button.disabled, str(button.label)), (False, "Collect"))
            # No message when it worked: the time by the button tells
            self.assertNotIn("slack: 2 items", str(app.query_one("FooterMessage").render()))
            # c does the same; a failure says why
            popen = fake_popen(1, "", "taf watch: another collect is running")
            with patch("taf.widgets.watch_tab.subprocess.Popen", popen):
                await pilot.press("c")
                await app.workers.wait_for_complete()
                await pilot.pause()
            self.assertEqual(len(popen.started), 1)
            self.assertIn("another collect is running", str(app.query_one("FooterMessage").render()))
            # When the last collect ended, by the button; nothing while one runs
            label = app.query_one("#collected-at", Static)
            self.assertEqual(str(label.render()), "")
            record_run(self.db, "slack", now(), 0.05, 1, 0, None)
            tab = app.query_one("#watch-view", WatchTab)
            tab.read_collected_at()
            self.assertEqual(str(label.render()), "just now")
            tab.collecting = True
            tab.show_collected_at()
            self.assertEqual(str(label.render()), "")
            tab.collecting = False
            # Only on Watch
            await pilot.press("tab")
            await pilot.pause()
            self.assertFalse(button.display or label.display)

        self.run_app(body)


class TodosViewTest(AppCase):
    TAB = "todos"

    def test_the_list_and_its_keys(self) -> None:
        async def body(app, pilot) -> None:
            renew, review, plan = self.made
            for minute, todo in enumerate((renew, review, plan)):
                self.db.execute("UPDATE notes SET updated_at = ? WHERE id = ?", (f"2026-09-30 10:0{minute}:00.000000", todo.id))
            set_pinned(self.db, renew.id, True)
            await pilot.press("r")
            await pilot.pause()
            # The last updated first; pinned or not
            self.assertEqual(self.summaries(app), ["Plan the trip", "Review the PR #work", "Renew passport #home"])
            self.assertEqual([row[1] for row in self.rows(app)], ["\U000f0131  ☆", "\U000f0131  ☆", "\U000f0131  ★"])
            self.assertEqual(self.status(app), "3 open todos")
            self.assertTrue(app.query_one("#todos-view").query_one(NotesTable).has_focus)

            # x marks the highlighted one done in its row: it leaves the open list on the next load
            await pilot.press("j", "x")
            await pilot.pause()
            self.assertEqual(self.summaries(app), ["Plan the trip", "Review the PR #work", "Renew passport #home"])
            self.assertEqual(self.rows(app)[1][1], "\U000f0132  ☆")
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
            self.assertEqual(self.rows(app)[0][1], "\U000f0131  ★")
            await pilot.press("space", "r")
            await pilot.pause()
            self.assertEqual(self.rows(app)[0][1], "\U000f0131  ☆")
            self.assertEqual(self.summaries(app), ["Plan the trip", "Review the PR #work", "Renew passport #home"])
            self.assertEqual(app.query_one("#todos-view").query_one(NotesTable).cursor_row, 0)

            # / searches, Enter runs it and goes back to the list
            await pilot.press("slash")
            self.assertTrue(app.query_one("#todos-view").query_one("#search", Input).has_focus)
            await pilot.press(*"PASS", "enter")
            await pilot.pause()
            self.assertEqual((self.summaries(app), self.status(app)), (["Renew passport #home"], "1 todo matching 'PASS'"))
            self.assertTrue(app.query_one("#todos-view").query_one(NotesTable).has_focus)

            # The Tags dropdown lists the tags with counts; picking one adds it to the search
            tags = app.query_one("#todos-view").query_one("#tag-selector", Select)
            # No "Tags" placeholder in the list: Any stands for no tag
            self.assertEqual([str(prompt) for prompt, _ in tags._options], ["Any tag", "home (1)", "work (1)"])
            self.assertEqual(tags.value, "any tag")
            app.query_one("#todos-view").query_one("#search", Input).value = ""
            tags.value = "work"
            await pilot.pause()
            self.assertEqual((app.query_one("#todos-view").query_one("#search", Input).value, self.summaries(app)), ("#work", ["Review the PR #work"]))
            # It shows the search's tag, as the status dropdown shows its status
            self.assertEqual(tags.value, "work")
            # Another tag takes the place of the one in the search; its words stay
            app.query_one("#todos-view").query_one("#search", Input).value = "renew #work"
            tags.value = "home"
            await pilot.pause()
            self.assertEqual((app.query_one("#todos-view").query_one("#search", Input).value, self.summaries(app)), ("renew #home", ["Renew passport #home"]))
            # Any takes the tag out, as All does the status
            app.query_one("#todos-view").query_one("#search", Input).value = "is:open renew #home"
            tags.value = "any tag"
            await pilot.pause()
            self.assertEqual((app.query_one("#todos-view").query_one("#search", Input).value, self.summaries(app)), ("is:open renew", ["Renew passport #home"]))
            self.assertEqual(tags.value, "any tag")
            # A tag typed in the search shows there too; one no todo has shows as Any, and stays in the search
            for typed, shown in (("#home", "home"), ("#ghost", "any tag")):
                await pilot.press("slash")
                app.query_one("#todos-view").query_one("#search", Input).value = typed
                await pilot.press("enter")
                await pilot.pause()
                self.assertEqual((tags.value, app.query_one("#todos-view").query_one("#search", Input).value), (shown, typed))

        self.run_app(body, todos=("Renew passport #home", "Review the PR #work", "Plan the trip"))

    def test_the_status_lives_in_the_search_as_is_open_or_is_done(self) -> None:
        async def body(app, pilot) -> None:
            search = app.query_one("#todos-view").query_one("#search", Input)
            status = app.query_one("#todos-view").query_one("#todo-status", Select)
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
            # Written elsewhere, say by taf todo, it shows once refreshed
            create_note(self.db, "Written from the shell", TODO)
            self.assertEqual(self.summaries(app), ["Old one"])
            await pilot.click("#btn-refresh")
            await pilot.pause()
            self.assertEqual(self.summaries(app), ["Written from the shell", "Old one"])
            self.assertTrue(app.query_one("#todos-view").query_one(NotesTable).has_focus)
            # Not on a todo, nor on Stats; on the logs and the notes' list too
            await pilot.press("enter")
            await pilot.pause()
            self.assertFalse(refresh.display)
            await pilot.press("escape")
            await pilot.pause()
            self.assertTrue(refresh.display)
            # On the notes' list and the logs too, not on the stats
            await pilot.press("tab")
            await pilot.pause()
            self.assertTrue(refresh.display)
            await pilot.press("tab")
            await pilot.pause()
            self.assertTrue(refresh.display)
            await pilot.press("tab")
            await pilot.pause()
            self.assertFalse(refresh.display)

        self.run_app(body, todos=("Old one",))

    def test_clicks_on_the_box_the_star_and_a_tag(self) -> None:
        async def body(app, pilot) -> None:
            table = app.query_one("#todos-view").query_one(NotesTable)
            # Past the id, the box's half of its column, then the star's
            await pilot.click(table, offset=(4, 0))
            await pilot.pause()
            self.assertEqual(self.rows(app)[0][1], "\U000f0132  ☆")
            await pilot.click(table, offset=(7, 0))
            await pilot.pause()
            [todo] = list_notes(self.db, TODO, status="all")
            self.assertEqual((todo.done, todo.pinned), (True, True))
            # A tag filters on it
            await pilot.click(table, offset=(10, 0))
            await pilot.pause()
            self.assertEqual(app.query_one("#todos-view").query_one("#search", Input).value, "is:open #home")

        self.run_app(body, todos=("#home chores",))

    def test_new_edit_and_delete_go_through_the_editor(self) -> None:
        async def body(app, pilot) -> None:
            seen = Path(tempfile.gettempdir()) / f"taf-test-seen-{id(self)}"
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
            todo = list_notes(self.db, TODO, status="open")[0]
            self.assertEqual(
                seen.read_text(),
                f"---\nid         : {todo.id}\ncreated_at : {todo.created_at:%Y-%m-%d %H:%M}\nupdated_at : {todo.updated_at:%Y-%m-%d %H:%M}\n"
                "done_at    :\npinned     : false\n---\n\nBuy milk #home",
            )
            self.assertEqual(self.summaries(app), ["Buy oat milk #home #shop", "Old one"])
            self.assertEqual(list_notes(self.db, TODO, status="open")[0].tags, ("home", "shop"))

            # Pinned and done show too
            todo = list_notes(self.db, TODO, status="open")[0]
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
            # Close, then the blue Edit, on the date's line
            close_button = detail.query_one("#btn-close-note")
            edit_button = detail.query_one("#btn-edit")
            date_line = detail.query_one("#note-detail-date")
            self.assertTrue(close_button.display and edit_button.display)
            self.assertEqual({close_button.region.y, edit_button.region.y}, {date_line.region.y})
            self.assertLess(date_line.region.x, close_button.region.x)
            self.assertLess(close_button.region.right, edit_button.region.x)
            self.assertTrue(edit_button.has_class("tinted"))
            todo = list_notes(self.db, TODO, status="open")[0]
            self.assertTrue(detail.display)
            self.assertFalse(app.query_one("#todos-view").query_one("#notes-list").display)
            self.assertTrue(edit_button.display)
            # The star, outlined, then when it was last updated
            star = app.query_one("#todos-view").query_one("#note-detail-pin", Static)
            date = app.query_one("#todos-view").query_one("#note-detail-date", Static)
            self.assertEqual(str(star.render()).strip(), "☆")
            self.assertEqual(str(date.render()), f"Updated {long_date(todo.updated_at)}")
            # A click on the star pins, there and in the list, and leaves "Updated" as it was
            await pilot.click(star)
            await pilot.pause()
            self.assertEqual((str(star.render()).strip(), star.has_class("-pinned")), ("★", True))
            self.assertTrue(list_notes(self.db, TODO, status="open")[0].pinned)
            self.assertEqual(self.rows(app)[0][1], "\U000f0131  ★")
            self.assertEqual(str(date.render()), f"Updated {long_date(todo.updated_at)}")
            await pilot.click(star)
            await pilot.pause()
            self.assertEqual((str(star.render()).strip(), list_notes(self.db, TODO, status="open")[0].pinned), ("☆", False))
            # The box marks done and back, there and in the list, the date still "Updated"
            box = app.query_one("#todos-view").query_one("#note-detail-done", Static)
            self.assertEqual(str(box.render()).strip(), "\U000f0131")
            await pilot.click(box)
            await pilot.pause()
            self.assertEqual(str(box.render()).strip(), "\U000f0132")
            self.assertTrue(list_notes(self.db, TODO, status="done"))
            self.assertEqual(self.rows(app)[0][1], "\U000f0132  ☆")
            self.assertEqual(str(date.render()), f"Updated {long_date(todo.updated_at)}")
            await pilot.click(box)
            await pilot.pause()
            self.assertEqual(str(box.render()).strip(), "\U000f0131")
            self.assertFalse(list_notes(self.db, TODO, status="done"))
            markdown = app.query_one("#todos-view").query_one("#note-detail-markdown")
            self.assertIn("uv run taf", markdown.source)
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
                await pilot.click(edit_button)
                await pilot.pause()
            self.assertEqual(markdown.source, "Shipped")

            # Another tab and back, the todo still shows
            await pilot.press("tab", "tab", "tab", "tab", "tab")
            await pilot.pause()
            self.assertTrue(detail.display)

            # Close goes back to the list, as does Escape
            await pilot.click(close_button)
            await pilot.pause()
            self.assertFalse(detail.display)
            await pilot.press("enter")
            await pilot.pause()
            self.assertTrue(detail.display)
            await pilot.press("escape")
            await pilot.pause()
            self.assertFalse(detail.display)
            self.assertTrue(app.query_one("#todos-view").query_one(NotesTable).has_focus)
            self.assertEqual(self.summaries(app), ["Shipped"])

            # Shift+Enter edits from the list, and saving stays on the list
            with patch.dict("os.environ", {"EDITOR": writes("Shipped twice")}):
                await pilot.press("shift+enter")
                await pilot.pause()
            self.assertFalse(detail.display)
            self.assertEqual(self.summaries(app), ["Shipped twice"])

            # The red Delete, after Edit at the right end of the line, asks first; Cancel keeps the todo on show
            await pilot.press("enter")
            await pilot.pause()
            delete_button = detail.query_one("#btn-delete")
            self.assertTrue(delete_button.display and delete_button.has_class("tinted", "-red"))
            self.assertLess(edit_button.region.right, delete_button.region.x)
            self.assertEqual(delete_button.region.right, detail.content_region.right)
            await pilot.click(delete_button)
            await pilot.pause()
            self.assertIsInstance(app.screen, ConfirmDialog)
            await pilot.press("enter")  # Cancel has focus
            await pilot.pause()
            self.assertTrue(detail.display)
            # Confirmed, it is gone and the list is back, without Delete
            await pilot.click(delete_button)
            await pilot.pause()
            await pilot.click("#confirm-btn")
            await pilot.pause()
            self.assertFalse(detail.display)
            self.assertEqual(self.summaries(app), [])
            self.assertEqual(list_notes(self.db, TODO, status="all"), [])

        self.run_app(body, todos=("# Release #work\n\n```bash\nuv run taf\n```",))

    def test_done_todos_are_gray_and_the_colors_follow_the_theme(self) -> None:
        async def body(app, pilot) -> None:
            set_done(self.db, self.made[0].id, True)
            await pilot.press("f", "r")
            await pilot.pause()
            app.apply_theme("dracula")
            await pilot.pause()
            summary = app.query_one("#todos-view").query_one(NotesTable).get_row_at(0)[-1]
            self.assertIn("#6272a4", str(summary.spans[-1].style).lower())

        self.run_app(body, todos=("Done one #home",))


class NotesViewTest(AppCase):
    def test_notes_have_a_star_but_no_status_and_their_tags_add_up(self) -> None:
        async def body(app, pilot) -> None:
            # The first tab
            self.assertEqual(app.tab, "notes")
            tab = app.query_one("#notes-view", NotesTab)
            table = tab.query_one(NotesTable)
            search = tab.query_one("#search", Input)
            rows = lambda: [[str(cell).strip() for cell in table.get_row_at(row)] for row in range(table.row_count)]  # noqa: E731
            # Only the notes: the todo stays on Todos; a star, no box, and no status anywhere
            self.assertTrue(table.has_focus)
            self.assertEqual(rows(), [["3", "☆", "Wifi is on the fridge #home #wifi"], ["2", "☆", "Car insurance #home #car"]])
            self.assertEqual((search.value, str(tab.query_one("#notes-status", Static).render())), ("", "2 notes"))
            self.assertFalse(tab.query("#todo-status"))
            await pilot.press("x", "f", "p")
            await pilot.pause()
            self.assertEqual(rows()[0][1], "★")
            self.assertEqual(search.value, "")
            await pilot.click(table, offset=(4, 1))
            await pilot.pause()
            self.assertEqual(rows()[1][1], "★")
            # Tags add up, from a click or the dropdown; Any takes them all out
            await pilot.click(table, offset=(30, 0))
            await pilot.pause()
            self.assertEqual(search.value, "#home")
            tags = tab.query_one("#tag-selector", Select)
            self.assertEqual([str(prompt) for prompt, _ in tags._options], ["Any tag", "home (2)", "car (1)", "wifi (1)"])
            tags.value = "wifi"
            await pilot.pause()
            self.assertEqual((search.value, rows()), ("#home #wifi", [["3", "★", "Wifi is on the fridge #home #wifi"]]))
            tags.value = "any tag"
            await pilot.pause()
            self.assertEqual((search.value, len(rows())), ("", 2))

            # A new note is a note, its front matter without done_at; its view has the star, not the box
            seen = Path(tempfile.gettempdir()) / f"taf-test-seen-{id(self)}"
            self.addCleanup(seen.unlink, missing_ok=True)
            code = f"import sys, shutil; shutil.copy(sys.argv[1], {str(seen)!r}); open(sys.argv[1], 'w').write('Gate code #home')"
            with patch.dict("os.environ", {"EDITOR": python_editor(code)}):
                await pilot.press("n")
                await pilot.pause()
                self.assertEqual([note.content for note in list_notes(self.db, NOTE)][0], "Gate code #home")
                await pilot.press("e")
                await pilot.pause()
            self.assertNotIn("done_at", seen.read_text())
            await pilot.press("enter")
            await pilot.pause()
            detail = tab.query_one(NoteDetail)
            self.assertTrue(detail.display)
            self.assertFalse(detail.query("#note-detail-done"))
            self.assertEqual(str(detail.query_one("#note-detail-pin", Static).render()).strip(), "☆")
            self.assertEqual(str(detail.query_one("#note-detail-id", Static).render()), "#4")
            # Delete, on the date's line, as for a todo
            await pilot.click(detail.query_one("#btn-delete"))
            await pilot.pause()
            await pilot.click("#confirm-btn")
            await pilot.pause()
            self.assertFalse(detail.display)
            self.assertEqual(len(list_notes(self.db, NOTE)), 2)
            self.assertEqual(len(list_notes(self.db, TODO)), 1)

        self.run_app(body, todos=("A todo #home",), notes=("Car insurance #home #car", "Wifi is on the fridge #home #wifi"))


if __name__ == "__main__":
    unittest.main()
