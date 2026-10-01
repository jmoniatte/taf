import asyncio
import re
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from textual.widgets import Static, TabbedContent
from tui_kit import shortcuts
from tui_kit.help_screen import HelpScreen
from tui_kit.theme import list_themes, load_palette

from fini.app import TABS, FiniApp, FooterMessage, load_stylesheet
from fini.config import Config
from fini.database import open_database
from fini.widgets import LogsScroll

# The Logs tab shows the last 7 days, so the logs are dated from today
TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)
LOGS = (
    ("Met with Brian @30m", f"{YESTERDAY} 09:00:00.000000", "Met with Brian", "meet", "rails", 30),
    ("Reviewed PR [chat] @15m", f"{TODAY} 15:14:26.000000", "Reviewed PR [chat]", "review", "rails", 15),
    ("PR for deleted users @1h45", f"{TODAY} 15:13:08.000000", "PR for deleted users", "code", "rails", 105),
    ("Admin stuff", f"{YESTERDAY} 10:00:00.000000", "Admin stuff", "admin", None, None),
    # Eight days ago: too old to show
    ("Old news", f"{TODAY - timedelta(days=7)} 23:59:00.000000", "Old news", "code", "rails", 5),
)


class AppTest(unittest.TestCase):
    def run_app(self, body, config: Config | None = None, logs=()) -> None:
        config = config or Config(theme="onedark")

        async def main() -> None:
            with tempfile.TemporaryDirectory() as tmp:
                # Never the user's database
                config.database_path = Path(tmp) / "fini.sqlite3"
                with open_database(config.database_path) as database:
                    database.executemany(
                        "INSERT INTO logs (message, logged_at, text, action, context, duration, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        [(*log, log[1]) for log in logs],
                    )
                database.close()
                app = FiniApp(config)
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
            self.assertEqual([str(tabs.get_tab(f"{name}-tab").label) for name in TABS], ["Todos", "Logs"])
            self.assertEqual((app.tab, tabs.active), ("todos", "todos-tab"))
            self.assertFalse(app.tabs.can_focus)
            await pilot.press("tab")
            await pilot.pause()
            self.assertEqual((app.tab, tabs.active), ("logs", "logs-tab"))
            # The list takes focus for its keys
            self.assertIsInstance(app.focused, LogsScroll)
            await pilot.press("tab")
            await pilot.pause()
            self.assertEqual(app.tab, "todos")
            self.assertIsNone(app.focused)

        self.run_app(body)

    def test_logs_show_by_day_like_the_ruby_fini(self) -> None:
        async def body(app, pilot) -> None:
            await pilot.press("tab")
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
            self.assertIn(f"[rgb(255,85,85)]{TODAY}", text.render().markup)
            self.assertEqual(load_palette("dracula")["red"].lower(), "#ff5555")

        self.run_app(body, logs=LOGS)

    def test_logs_can_be_selected_with_the_mouse_and_copied_with_y(self) -> None:
        async def body(app, pilot) -> None:
            await pilot.press("tab")
            await pilot.pause()
            text = app.query_one("#logs-text", Static)
            # From "15:13" on the first log to "Reviewed PR" on the second
            await pilot.mouse_down(text, offset=(2, 1))
            await pilot.hover(text, offset=(20, 2))
            await pilot.mouse_up(text, offset=(20, 2))
            await pilot.pause()
            selected = "15:13 - PR for deleted users 1h45 [+code @rails]\n* 15:14 - Reviewed PR"
            self.assertEqual(app.screen.get_selected_text(), selected)
            copied = []
            app.copy_to_clipboard = copied.append
            await pilot.press("y")
            self.assertEqual(copied, [selected])

        self.run_app(body, logs=LOGS)

    def test_no_logs_and_a_database_that_cannot_open_say_so(self) -> None:
        async def body(app, pilot) -> None:
            self.assertEqual(app.query_one("#logs-empty", Static).render().plain, "No logs in the last 7 days")
            self.assertFalse(app.query_one(LogsScroll).display)

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

    def test_help_lists_every_key_and_tab_does_nothing_under_it(self) -> None:
        async def body(app, pilot) -> None:
            await pilot.press("?")
            await pilot.pause()
            self.assertIsInstance(app.screen, HelpScreen)
            keys = {static.content for static in app.screen.query(".shortcut-key")}
            expected = {
                shortcut.key
                for section in shortcuts.SECTIONS
                for shortcut in shortcuts.for_section(section, LogsScroll.BINDINGS, app.BINDINGS)
            }
            self.assertEqual(keys, expected)
            self.assertTrue({"?", "t", "y", "tab", "q", "j", "k"} <= keys)
            await pilot.press("tab")
            await pilot.pause()
            self.assertEqual(app.tab, "todos")

        self.run_app(body)

    def test_a_message_takes_helps_place_until_it_clears_and_close_quits(self) -> None:
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
            await pilot.press("escape")
            await pilot.pause()
            await pilot.click("#btn-close")
            await pilot.pause()
            self.assertFalse(app.is_running)

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
