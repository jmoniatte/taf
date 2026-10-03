import asyncio
import re
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from textual.widgets import Input, Select, Static, TabbedContent
from tui_kit.help_screen import HelpScreen
from tui_kit.theme import list_themes, load_palette

from fini.app import TABS, FiniApp, FooterMessage, load_stylesheet
from fini.config import Config
from fini.database import open_database
from fini.logs import create_log
from fini.message import Inference
from fini.notes import TODO, create_note
from fini.widgets.stats_view import ALL_ACTIONS
from fini.widgets import LogsScroll, LogsView, NotesTab, NotesTable, StatsScroll, StatsView, TodosTab
from fini.widgets.logs_view import HINT, NewLogScreen
from test_notes_view import python_editor, suspend, writes

# The Logs tab shows the last 7 days, so the logs are dated from today


def logs_around(today: date) -> tuple:
    yesterday = today - timedelta(days=1)
    return (
        ("Met with Brian @30m", f"{yesterday} 09:00:00.000000", "Met with Brian", "meet", "rails", 30),
        ("Reviewed PR [chat] @15m", f"{today} 15:14:26.000000", "Reviewed PR [chat]", "review", "rails", 15),
        ("PR for deleted users @1h45", f"{today} 15:13:08.000000", "PR for deleted users", "code", "rails", 105),
        ("Admin stuff", f"{yesterday} 10:00:00.000000", "Admin stuff", "admin", None, None),
        # A week before
        ("Old news", f"{today - timedelta(days=7)} 23:59:00.000000", "Old news", "code", "rails", 5),
    )


# The Logs tab shows this week, Monday to Sunday: its tests say today is Thursday, October 1, 2026, in week 40
TODAY = date(2026, 10, 1)
YESTERDAY = TODAY - timedelta(days=1)
LOGS = logs_around(TODAY)
# The Stats tab counts from the real today
REAL_TODAY = date.today()
STATS_LOGS = logs_around(REAL_TODAY)


class AppTest(unittest.TestCase):
    def run_app(self, body, config: Config | None = None, logs=()) -> None:
        config = config or Config(theme="onedark")

        async def main() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                # Never the user's database
                config.database_path = Path(tmp) / "fini.sqlite3"
                config.path = Path(tmp) / "config.yml"
                with open_database(config.database_path) as database:
                    database.executemany(
                        "INSERT INTO logs (message, logged_at, text, action, context, duration, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [(*log, log[1]) for log in logs],
                    )
                database.close()
                app = FiniApp(config)
                # The fixed logs' week is this one; without them, logs are written now
                with patch("fini.widgets.logs_view.today", return_value=TODAY if logs is LOGS else REAL_TODAY):
                    async with app.run_test(size=(80, 24)) as pilot:
                        await pilot.pause()
                        await body(app, pilot)

        asyncio.run(main())

    def test_tabs_on_the_first_row_and_tab_moves_to_the_next(self) -> None:
        async def body(app, pilot) -> None:
            tabs = app.query_one("#tabs", TabbedContent)
            # No title bar
            self.assertFalse(app.query("#app-header"))
            self.assertEqual(tabs.region.y, 0)
            self.assertEqual([str(tabs.get_tab(f"{name}-tab").label) for name in TABS], ["Notes", "Todos", "Logs", "Stats"])
            self.assertEqual((app.tab, tabs.active), ("notes", "notes-tab"))
            self.assertFalse(app.tabs.can_focus)
            # The list takes focus for its keys
            self.assertIsInstance(app.focused, NotesTable)
            await pilot.press("tab")
            await pilot.pause()
            self.assertEqual((app.tab, tabs.active), ("todos", "todos-tab"))
            self.assertIsInstance(app.focused.parent.parent, TodosTab)
            await pilot.press("tab")
            await pilot.pause()
            self.assertEqual((app.tab, tabs.active), ("logs", "logs-tab"))
            self.assertIsInstance(app.focused, LogsScroll)
            await pilot.press("tab", "tab")
            await pilot.pause()
            self.assertEqual(app.tab, "notes")
            self.assertIsInstance(app.focused.parent.parent, NotesTab)

        self.run_app(body)

    def test_logs_show_by_day_like_the_ruby_fini(self) -> None:
        async def body(app, pilot) -> None:
            await pilot.press("tab", "tab")
            await pilot.pause()
            text = app.query_one("#logs-text", Static)
            self.assertEqual(
                str(text.render()).splitlines(),
                [
                    f"{TODAY} - {TODAY:%A} 2h",
                    "* 15:13 - PR for deleted users 1h45 [+code @rails]",
                    "* 15:14 - Reviewed PR [chat] 15m [+review @rails]",
                    "",
                    f"{YESTERDAY} - {YESTERDAY:%A} 30m",
                    "* 09:00 - Met with Brian 30m [+meet @rails]",
                    "* 10:00 - Admin stuff [+admin]",
                ],
            )
            self.assertFalse(app.query_one("#logs-empty").display)
            # The colors follow a theme change
            app.apply_theme("dracula")
            await pilot.pause()
            self.assertIn(f"[rgb(255,85,85) @click='edit_day('{TODAY}')']{TODAY}", text.render().markup)
            self.assertEqual(load_palette("dracula")["red"].lower(), "#ff5555")

        self.run_app(body, logs=LOGS)

    def test_logs_can_be_selected_with_the_mouse_and_copied_with_y(self) -> None:
        async def body(app, pilot) -> None:
            await pilot.press("tab", "tab")
            await pilot.pause()
            text = app.query_one("#logs-text", Static)
            # From "15:13" on the first log to "Reviewed PR" on the second
            await pilot.mouse_down(text, offset=(2, 1))
            await pilot.hover(text, offset=(20, 2))
            await pilot.mouse_up(text, offset=(20, 2))
            await pilot.pause()
            selected = "15:13 - PR for deleted users 1h45 [+code @rails]\n* 15:14 - Reviewed PR"
            self.assertEqual(app.screen.get_selected_text(), selected)
            # A drag that ends on a day's date selects, and does not edit the day
            await pilot.mouse_down(text, offset=(20, 2))
            await pilot.hover(text, offset=(5, 4))
            await pilot.mouse_up(text, offset=(5, 4))
            await pilot.pause()
            self.assertTrue(app.screen.get_selected_text())
            self.assertFalse(app.query_one(FooterMessage).display)
            await pilot.mouse_down(text, offset=(2, 1))
            await pilot.hover(text, offset=(20, 2))
            await pilot.mouse_up(text, offset=(20, 2))
            await pilot.pause()
            copied = []
            app.copy_to_clipboard = copied.append
            await pilot.press("y")
            self.assertEqual(copied, [selected])

        self.run_app(body, logs=LOGS)

    def test_no_logs_and_a_database_that_cannot_open_say_so(self) -> None:
        async def body(app, pilot) -> None:
            self.assertEqual(app.query_one("#logs-empty", Static).render().plain, f"No logs in week {REAL_TODAY.isocalendar().week}")
            self.assertFalse(str(app.query_one("#logs-text", Static).render()))

        self.run_app(body)

        async def broken(app, pilot) -> None:
            self.assertIsNone(app.database)
            self.assertIn("Cannot open the database", app.query_one("#logs-empty", Static).render().plain)
            self.assertIn("Cannot open the database", app.query_one(FooterMessage).render().plain)

        with tempfile.TemporaryDirectory() as tmp:
            # A folder where the file should be
            app = FiniApp(Config(theme="onedark", database_path=Path(tmp)))

            async def main() -> None:
                async with app.run_test(size=(80, 24)) as pilot:
                    await pilot.pause()
                    await broken(app, pilot)

            asyncio.run(main())

    def test_new_log_opens_a_window_that_reads_the_message_on_every_key(self) -> None:
        async def body(app, pilot) -> None:
            await pilot.press("tab", "tab")
            await pilot.pause()
            # Escape closes the window and logs nothing
            await pilot.press("n", *"Met", "escape")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, NewLogScreen)
            await pilot.click("#btn-new-log")
            await pilot.pause()
            self.assertIsInstance(app.screen, NewLogScreen)
            preview = app.screen.query_one("#log-preview", Static)
            box = app.screen.query_one("#log-input", Input)
            self.assertTrue(box.has_focus)
            self.assertEqual(preview.render().plain, HINT)
            await pilot.press(*"Met Bob @20")
            await pilot.pause()
            # Not a duration yet: a context
            self.assertEqual(preview.render().plain, "Met Bob [+meet @20]")
            await pilot.press("m")
            await pilot.pause()
            self.assertEqual(preview.render().plain, "Met Bob 20m [+meet @rails]")
            await pilot.press("enter")
            await pilot.pause()
            self.assertNotIsInstance(app.screen, NewLogScreen)
            self.assertIsInstance(app.focused, LogsScroll)
            self.assertIn("Met Bob 20m [+meet @rails]", str(app.query_one("#logs-text", Static).render()))
            self.assertEqual(app.query_one(FooterMessage).render().plain.strip(), "Logged: Met Bob 20m [+meet @rails]")
            stored = app.database.execute("SELECT message, text, action, context, duration FROM logs").fetchall()
            self.assertEqual([tuple(row) for row in stored], [("Met Bob @20m", "Met Bob", "meet", "rails", 20)])

        rules = Config(theme="onedark", action=Inference("code", [("meet", [re.compile(r"^Met\b")])]), context=Inference("rails"))
        self.run_app(body, config=rules)

    def test_the_logs_page_by_week_from_monday(self) -> None:
        async def body(app, pilot) -> None:
            await pilot.press("tab", "tab")
            await pilot.pause()
            dates = app.query_one("#logs-dates", Static)
            week = app.query_one("#logs-week-number", Static)
            previous = app.query_one("#btn-previous-week")
            text = app.query_one("#logs-text", Static)
            next_week = app.query_one("#btn-next-week")
            self.assertEqual((dates.render().plain, week.render().plain), ("Sep 28 to Oct 4, 2026", "Week 40"))
            # Previous and Next stay put whatever the length of the dates
            places = (previous.region.x, next_week.region.x)
            # Nothing after this week
            self.assertTrue(next_week.disabled)
            await pilot.press("right_square_bracket")
            await pilot.pause()
            self.assertEqual(app.query_one(LogsView).page, 0)
            await pilot.click("#btn-previous-week")
            await pilot.pause()
            self.assertEqual((dates.render().plain, week.render().plain), ("Sep 21 to Sep 27, 2026", "Week 39"))
            self.assertEqual((previous.region.x, next_week.region.x), places)
            self.assertFalse(next_week.disabled)
            self.assertEqual(str(text.render()).splitlines()[1], "* 23:59 - Old news 5m [+code @rails]")
            # The logs keep focus for the keys
            self.assertIsInstance(app.focused, LogsScroll)
            await pilot.press("left_square_bracket")
            await pilot.pause()
            empty = app.query_one("#logs-empty", Static)
            self.assertTrue(empty.display)
            self.assertEqual(empty.render().plain, "No logs in week 38")
            await pilot.click("#btn-next-week")
            await pilot.press("right_square_bracket")
            await pilot.pause()
            self.assertIn("Met with Brian", str(text.render()))

        self.run_app(body, logs=LOGS)

    def test_e_or_a_click_edits_a_day_and_refresh_reads_them_again(self) -> None:
        async def body(app, pilot) -> None:
            await pilot.press("tab", "tab")
            await pilot.pause()
            seen = Path(app.config.database_path).parent / "seen.md"

            def editor(old: str, new: str) -> str:
                """Keeps a copy of the file as the editor got it, then replaces old with new."""
                return python_editor(
                    f"import sys, shutil; shutil.copy(sys.argv[1], {str(seen)!r}); path = sys.argv[1]"
                    f"; text = open(path).read().replace({old!r}, {new!r}); open(path, 'w').write(text)"
                )

            def stored() -> list[str]:
                return [row["text"] for row in app.database.execute("SELECT text FROM logs ORDER BY logged_at")]

            # e edits the last day, today, alone
            with patch.dict("os.environ", {"EDITOR": editor("Reviewed PR [chat] @15m", "Reviewed PR @20m")}):
                await pilot.press("e")
                await pilot.pause()
            self.assertEqual(
                seen.read_text(), f"# {TODAY} - {TODAY:%A}\n* 15:13 - PR for deleted users @1h45\n* 15:14 - Reviewed PR [chat] @15m"
            )
            self.assertIn("* 15:14 - Reviewed PR 20m", str(app.query_one("#logs-text", Static).render()))
            self.assertEqual(app.query_one(FooterMessage).render().plain.strip(), f"Logs of {TODAY:%A} {TODAY:%b} {TODAY.day} updated")
            # A click on yesterday's date, under today's header, 2 logs and a blank line, edits yesterday
            text = app.query_one("#logs-text", Static)
            with patch.dict("os.environ", {"EDITOR": editor("\n* 10:00 - Admin stuff", "")}):
                await pilot.click(text, offset=(3, 4))
                await pilot.pause()
            self.assertTrue(seen.read_text().startswith(f"# {YESTERDAY} - {YESTERDAY:%A}\n"))
            self.assertEqual(stored(), ["Old news", "Met with Brian", "PR for deleted users", "Reviewed PR"])
            # No logs in the week on show: its Sunday, under which a log can be written
            await pilot.press("left_square_bracket", "left_square_bracket")
            await pilot.pause()
            empty_day = date(2026, 9, 20)
            header = f"# {empty_day} - {empty_day:%A}"
            with patch.dict("os.environ", {"EDITOR": editor(header, f"{header}\n* 08:00 - Wrote docs @1h")}):
                await pilot.press("e")
                await pilot.pause()
            self.assertEqual(seen.read_text(), header)
            self.assertIn("* 08:00 - Wrote docs 1h", str(app.query_one("#logs-text", Static).render()))
            # A day with logs added under its own header saves nothing: its logs were never in the file
            with patch.dict("os.environ", {"EDITOR": editor(header, f"{header}\n\n# {YESTERDAY}\n* 08:00 - Moved")}):
                await pilot.press("e")
                await pilot.pause()
            message = app.query_one(FooterMessage).render().plain
            self.assertIn(f"{YESTERDAY} already has logs: edit it on its own. Nothing saved", message)
            Path(re.search(r"/\S+\.md", message.replace("\n", "")).group(0)).unlink()
            self.assertNotIn("Moved", stored())
            self.assertIn("Met with Brian", stored())
            # A day with no logs yet may be added
            with patch.dict("os.environ", {"EDITOR": editor("Wrote docs @1h", "Wrote docs @1h\n\n# 2026-09-19 - Saturday\n* 10:00 - Weekend deploy @1h")}):
                await pilot.press("e")
                await pilot.pause()
            self.assertEqual(app.query_one(FooterMessage).render().plain.strip(), "Logs of Sunday Sep 20, Saturday Sep 19 updated")
            self.assertIn("Weekend deploy", stored())
            self.assertIn("Wrote docs", stored())
            # A header removed by mistake saves nothing
            with patch.dict("os.environ", {"EDITOR": editor(header, "")}):
                await pilot.press("e")
                await pilot.pause()
            message = app.query_one(FooterMessage).render().plain
            self.assertIn(f"The header of {empty_day} is gone. Nothing saved", message)
            Path(re.search(r"/\S+\.md", message.replace("\n", "")).group(0)).unlink()
            # A date that does not exist saves nothing and keeps the edit
            with patch.dict("os.environ", {"EDITOR": writes("# 2026-02-31 - Tuesday\n* 08:00 - Lost\n")}):
                await pilot.press("e")
                await pilot.pause()
            message = app.query_one(FooterMessage).render().plain
            self.assertIn("'# 2026-02-31 - Tuesday' has no valid date. Nothing saved; your edit is kept in", message)
            kept = Path(re.search(r"/\S+\.md", message.replace("\n", "")).group(0))
            self.assertIn("Lost", kept.read_text())
            kept.unlink()
            self.assertNotIn("Lost", stored())
            # Logged elsewhere, by fini log, it shows once refreshed
            await pilot.press("right_square_bracket", "right_square_bracket")
            create_log(app.database, "From the shell @5m")
            refresh = app.query_one("#btn-refresh")
            self.assertTrue(refresh.display)
            await pilot.click("#btn-refresh")
            await pilot.pause()
            self.assertIn("From the shell 5m", str(app.query_one("#logs-text", Static).render()))

        with patch("fini.app.FiniApp.suspend", suspend):
            self.run_app(body, logs=LOGS)

    def test_a_written_day_is_read_again_with_the_current_rules_even_unchanged(self) -> None:
        async def body(app, pilot) -> None:
            await pilot.press("tab", "tab")
            await pilot.pause()

            def actions() -> list[str]:
                return [row["action"] for row in app.database.execute("SELECT action FROM logs WHERE logged_at LIKE ? ORDER BY logged_at", (f"{YESTERDAY}%",))]

            # Quit without writing: nothing changes
            text = app.query_one("#logs-text", Static)
            with patch.dict("os.environ", {"EDITOR": python_editor("pass")}):
                await pilot.click(text, offset=(3, 4))
                await pilot.pause()
            self.assertEqual(actions(), ["meet", "admin"])
            # Written as it was: the rules of today's config name the actions again
            rewrite = python_editor("import sys; path = sys.argv[1]; text = open(path).read(); open(path, 'w').write(text)")
            with patch.dict("os.environ", {"EDITOR": rewrite}):
                await pilot.click(text, offset=(3, 4))
                await pilot.pause()
            self.assertEqual(actions(), ["talk", "talk"])

        with patch("fini.app.FiniApp.suspend", suspend):
            self.run_app(body, config=Config(theme="onedark", action=Inference("talk")), logs=LOGS)

    def test_a_database_error_on_logging_or_saving_keeps_the_work(self) -> None:
        async def body(app, pilot) -> None:
            await pilot.press("tab", "tab")
            await pilot.pause()
            locked = sqlite3.OperationalError("database is locked")
            with patch("fini.widgets.logs_view.create_log", side_effect=locked):
                await pilot.press("n", *"Coded @1h", "enter")
                await pilot.pause()
            # The window stays open with the message, and says why
            self.assertIsInstance(app.screen, NewLogScreen)
            self.assertEqual(app.screen.query_one("#log-preview", Static).render().plain, "Cannot log: database is locked")
            self.assertEqual(app.screen.query_one("#log-input", Input).value, "Coded @1h")
            await pilot.press("escape")
            await pilot.pause()
            with patch("fini.widgets.logs_view.replace_days", side_effect=locked), patch.dict("os.environ", {"EDITOR": writes(f"# {TODAY}\n* 08:00 - Kept\n")}):
                await pilot.press("e")
                await pilot.pause()
            message = app.query_one(FooterMessage).render().plain
            self.assertIn("Cannot save: database is locked. Your edit is kept in", message)
            kept = Path(re.search(r"/\S+\.md", message.replace("\n", "")).group(0))
            self.assertIn("Kept", kept.read_text())
            kept.unlink()
            self.assertTrue(app.is_running)

        with patch("fini.app.FiniApp.suspend", suspend):
            self.run_app(body, logs=LOGS)

    def test_help_shows_the_apps_keys_and_the_tabs_own(self) -> None:
        async def help_keys(app, pilot) -> dict[str, list[str]]:
            """Help's keys by column title, then Help closed again."""
            await pilot.press("question_mark")
            await pilot.pause()
            self.assertIsInstance(app.screen, HelpScreen)
            # The app's own Close must not hide Help's
            self.assertTrue(app.screen.query_one("#btn-close").display)
            columns = {
                str(column.query_one(".section-title").render()): [str(key.render()) for key in column.query(".shortcut-key")]
                for column in app.screen.query(".shortcuts-section")
            }
            # tab does nothing under Help
            await pilot.press("tab")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            return columns

        async def body(app, pilot) -> None:
            general = ["?", "t", "y", "tab", "q"]
            # Notes have no status: no x, no f
            self.assertEqual(
                await help_keys(app, pilot), {"GENERAL": general, "NOTES": ["n", "e", "⇧+enter", "p", "space", "/", "#", "r", "y", "enter", "j", "k"]}
            )
            await pilot.press("tab")
            await pilot.pause()
            self.assertEqual(
                await help_keys(app, pilot),
                {"GENERAL": general, "TODOS": ["n", "e", "⇧+enter", "x", "p", "space", "f", "/", "#", "r", "y", "enter", "j", "k"]},
            )
            self.assertEqual(app.tab, "todos")
            # One todo on show: its own keys
            with open_database(app.config.database_path) as database:
                create_note(database, "A todo", TODO)
            database.close()
            await pilot.press("r", "enter")
            await pilot.pause()
            self.assertEqual(await help_keys(app, pilot), {"GENERAL": general, "TODO": ["escape", "e", "⇧+enter", "y", "j", "k"]})
            await pilot.press("tab")
            await pilot.pause()
            self.assertEqual(await help_keys(app, pilot), {"GENERAL": general, "LOGS": ["n", "e", "[", "]", "r", "j", "k"]})
            # The footer's Help button opens the same
            await pilot.click("#btn-help")
            await pilot.pause()
            self.assertIn("LOGS", [str(title.render()) for title in app.screen.query(".section-title")])
            await pilot.press("escape", "tab")
            await pilot.pause()
            self.assertEqual(await help_keys(app, pilot), {"GENERAL": general, "STATS": ["j", "k"]})

        self.run_app(body)

    def test_stats_show_the_time_per_action_and_switch_period_and_action(self) -> None:
        async def body(app, pilot) -> None:
            await pilot.press("tab", "tab", "tab")
            await pilot.pause()
            self.assertIsInstance(app.focused, StatsScroll)
            period = app.query_one("#stats-period", Select)
            action = app.query_one("#stats-action", Select)
            self.assertEqual([str(option[0]) for option in period._options], ["Last 12 months", str(REAL_TODAY.year)][: len(period._options)])
            self.assertEqual(
                [str(option[0]) for option in action._options], ["All actions", "code (1.8 h)", "meet (0.5 h)", "review (0.2 h)"]
            )
            lines = str(app.query_one("#stats-text", Static).render()).splitlines()
            # Admin has no duration, so it adds no time
            self.assertEqual(lines[0], "2.6 h logged   3 days   0.8 h a day")
            self.assertIn("Mon ", lines[3])
            code = next(line for line in lines if line.startswith("code "))
            self.assertTrue(code.endswith("71%    1.8 h"), code)
            # Picking an action narrows the figures, and the list keeps its focus
            action.value = "code"
            await pilot.pause()
            lines = str(app.query_one("#stats-text", Static).render()).splitlines()
            self.assertEqual(lines[0], "1.8 h of +code   71% of the time   on 2 days   0.9 h on those days")
            self.assertIsInstance(app.focused, StatsScroll)
            # The year keeps the action
            period.value = 1
            await pilot.pause()
            self.assertEqual(app.query_one(StatsView).periods[1].label, str(REAL_TODAY.year))
            self.assertEqual(action.value, "code")

            # Percentages: no hours anywhere, and the choice is kept in the config
            period.value = 0
            app.query_one("#stats-show", Select).value = "percentages"
            await pilot.pause()
            text = str(app.query_one("#stats-text", Static).render())
            self.assertEqual(text.splitlines()[0], "+code 71% of the time")
            self.assertNotRegex(text, r"\d h\b")
            self.assertIn("code (71%)", [str(option[0]) for option in action._options])
            self.assertEqual(app.config.path.read_text(), "stats_show: percentages\n")
            action.value = ALL_ACTIONS
            await pilot.pause()
            text = str(app.query_one("#stats-text", Static).render())
            self.assertEqual(text.splitlines()[0], "code 71%   meet 19%   review 10%")
            self.assertNotRegex(text, r"\d h\b")

        self.run_app(body, logs=STATS_LOGS)

    def test_exit_sits_at_the_left_of_the_footer_and_quits(self) -> None:
        async def body(app, pilot) -> None:
            exit_button = app.query_one("#btn-exit")
            refresh = app.query_one("#btn-refresh")
            self.assertEqual((exit_button.region.y, exit_button.region.x), (app.size.height - 1, 1))
            self.assertLess(exit_button.region.right, refresh.region.x)
            self.assertEqual(str(exit_button.label), "Exit")
            self.assertTrue(exit_button.has_class("tinted", "-red"))
            await pilot.click("#btn-exit")
            await pilot.pause()
            self.assertFalse(app.is_running)

        self.run_app(body)

    def test_a_message_takes_helps_place_until_it_clears(self) -> None:
        async def body(app, pilot) -> None:
            footer = app.query_one("#app-footer")
            message = app.query_one(FooterMessage)
            help_button = app.query_one("#btn-help")
            self.assertEqual(footer.region.bottom, app.size.height)
            self.assertEqual(message.render().plain, "Config file is not valid YAML: oops")
            self.assertFalse(help_button.display)
            # On the last row, ending where Help ends, on the right
            self.assertEqual((message.region.right, message.region.y), (footer.content_region.right, app.size.height - 1))
            message.clear_notification()
            await pilot.pause()
            await pilot.pause()
            self.assertTrue(help_button.display)
            self.assertEqual(help_button.region.right, footer.content_region.right)
            self.assertFalse(message.display)

            await pilot.click("#btn-help")
            await pilot.pause()
            self.assertIsInstance(app.screen, HelpScreen)

        self.run_app(body, Config(theme="onedark", warnings=["Config file is not valid YAML: oops"]))


class ThemeTest(unittest.TestCase):
    def test_every_theme_fills_each_variable_the_stylesheets_use(self) -> None:
        required = set(re.findall(r"\$([\w-]+)", load_stylesheet()))
        self.assertIn("comment", required)
        for name in list_themes():
            with self.subTest(theme=name):
                self.assertEqual(required - set(load_palette(name)), set())


if __name__ == "__main__":
    unittest.main()
