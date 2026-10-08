import unittest
import unittest.mock
from unittest.mock import patch

from textual.widgets import Static

from taf.notes import long_date
from taf.watch.items import Item, get_item, now, record_run, save_item
from taf.watch.projects import add_project
from taf.watch.view import load_item
from taf.widgets import CollectControl, NotesTable, WatchDetail, WatchTab
from test_notes_view import AppCase, header


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
            # A heading per project from the left edge, a blank row between them; each item with its id
            self.assertEqual(lines, [
                " follow (1)", " 1  \U000f0131  ☆  Answer Kevin  \U000f04b1", "", " No project (1)", " 2  \U000f0131  ☆  CI fails on r#1  \uf2ec  \U000f02a4",
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
            # A new theme draws the headings and the blank row again, in its colors
            app.apply_theme("dracula")
            await pilot.pause()
            self.assertEqual(len(table.lines), 5)
            self.assertEqual(table.get_row_at(4)[2].spans[-1].style.color.name, app.palette["blue"])
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
            self.assertEqual(str(detail.query_one("#note-detail-id", Static).render()), "#1")
            # One line: "Watch >", a link back, the id, when it was saved, Slack's icon, then the box and the star
            created = long_date(load_item(self.db, 1).created_at)
            self.assertEqual(header(detail), f"Watch > #1 Created {created} \U000f04b1 \U000f0132 ★")
            links = [span.style.link for span in detail.query_one("#note-detail-links", Static).render().spans]
            self.assertEqual(links, ["https://slack/1"])
            self.assertFalse(detail.query("#btn-edit") or detail.query("#btn-delete"))
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
            self.assertTrue(app.query_one(CollectControl).display)
            popen = fake_popen(0, "github: 3 open PRs, 1 new items\nslack: 2 items", "")
            with patch("taf.widgets.collect.subprocess.Popen", popen):
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
            with patch("taf.widgets.collect.subprocess.Popen", popen):
                await pilot.press("c")
                await app.workers.wait_for_complete()
                await pilot.pause()
            self.assertEqual(len(popen.started), 1)
            self.assertIn("another collect is running", str(app.query_one("FooterMessage").render()))
            # When the last collect ended, by the button; nothing while one runs
            label = app.query_one("#collected-at", Static)
            self.assertEqual(str(label.render()), "")
            record_run(self.db, "slack", now(), 0.05, 1, 0, None)
            control = app.query_one(CollectControl)
            control.read_collected_at()
            self.assertEqual(str(label.render()), "just now")
            control.collecting = True
            control.show_collected_at()
            self.assertEqual(str(label.render()), "")
            control.collecting = False
            # Only on Watch
            await pilot.press("tab")
            await pilot.pause()
            self.assertFalse(control.display)

        self.run_app(body)


if __name__ == "__main__":
    unittest.main()
