# Fini

TUI for todos and a log of the work done ("fini" is French for "done"), both kept in one local
SQLite database. It replaces the Ruby fini CLI; master keeps the Ruby version until this branch
replaces it (`git show master:lib/fini/models/log/message_parser.rb` for its message parser).

It is built on [tui-kit](../tui-kit), shared with outils, flotte and yafyaf-tui: the themes and the
picker (`t`), the messages, Help (`?`), the dialogs, the startup check and the
buttons' look (the `tinted` class) all come from there. Code that every app would use goes in
tui-kit, not here; see its AGENTS.md. Like outils, it has no title bar (tui-kit's `AppHeader`): the
tabs are the first row, and every message goes to the footer.

## Rules

- Do not git commit unless asked
- The help screen lists every binding that has a description and a `group`
  (`tui_kit.shortcuts.ACTIONS` or `GENERAL`) in `FiniApp.BINDINGS` and `FiniApp.HELP_BINDINGS`;
  document a new key there
- Never hardcode a color in a `.tcss` file

## Run

```bash
fini
fini log Reviewed PR from Zach @20m     # log a message
fini log                                # today's logs
fini log -v 2                           # the last 2 days' logs
fini log -e 2                           # edit the last 2 days' logs in $EDITOR
```

`fini` refuses to start unless stdin and stdout are a terminal (tui-kit's `start`); `fini log`
does not go through that check.

## Test

Run both from the git root.

```bash
uv run python -m unittest discover -s tests
uv run ruff check .
```

There is no pytest. App tests point `database_path` at a temporary file (`run_app` in
`tests/test_app.py`); a test that builds `FiniApp` without one opens the user's real database.
`ruff` is pinned in the `dev` dependency group, so use `uv run ruff`.
tui-kit comes from GitHub's master (`[tool.uv.sources]`); after a push there,
`uv lock --upgrade-package tui-kit` picks it up. To work on both at once, switch that source to
the commented-out `../tui-kit` path.

## Structure

```
fini/                   # git root + pyproject.toml (run uv commands here)
  fini/                 # Python package
    __init__.py         # The version and the repository's URL
    __main__.py         # The command line: the TUI, or `fini log`'s own parser
    log_command.py      # `fini log`: log, view and edit in the shell, as the Ruby fini did; no Textual
    message.py          # A message's @duration, @context and +action, and the rules that infer the rest; no Textual
    app.py              # FiniApp, a tui-kit BaseApp: TABS, the footer and its messages, the keys
    config.py           # Optional ~/.config/fini/config.yml (theme, through tui_kit.config; database_path)
    database.py         # Opening the SQLite database and its migrations; no Textual
    logs.py             # Log, reading, creating and replacing logs, formatting a duration; no Textual
    widgets/            # One view per tab: todos_view.py, logs_view.py
    styles/fini.tcss    # fini's own styles, joined after tui-kit's (app.STYLE_FILES)
```

## Layout

The `#tabs` `TabbedContent` is the first row, one tab per entry in `TABS` (`app.py`): Todos,
then Logs. Each pane is `<name>-tab` and holds its view, `<name>-view`. A click
on a tab or `tab` switches; `tab` is an app binding with `priority`, so the screen's own `tab`
(focus next) never runs, and it is skipped while a panel or dialog is up. The tabs cannot take
focus, so a view keeps its keys. `FiniApp.tab` is the name of the tab on show. When a tab shows,
its first widget that can take focus gets it (the logs list), or nothing has focus. `AUTO_FOCUS`
is None: `TabbedContent` switches to the tab of whatever has focus, so Textual focusing the logs
list on start would open on Logs.

Under every tab, `#app-footer` is docked at the bottom: a rule (`border-top`) over Close, which
quits, on the left, and Help, which opens the shortcuts like `?`, on the right (`dock: right`).
Neither can take focus, so a click leaves the view's keys working. tui-kit shows messages in
whatever `HeaderNotification` the screen holds, so the footer holds one, `FooterMessage`: while a
message shows, it takes Help's place, right-aligned (an error wraps onto up to three lines), and
Help comes back once it clears. Copied from outils.

## Logs

`FiniApp` opens the database when built (`database.open_database`); when it cannot,
`FiniApp.database` is None, the error shows in the footer and in place of the list
(`database_error`). `LogsView` reads the logs of the last `DAYS` (7) days, today included, once mounted
(`logs.recent_logs`), like `fini -v 7` did, and shows them
the way the Ruby fini's `TerminalPresenter` printed them: the last day first, each day's logs in
the order they were logged, under a header with the day and the time spent on it all:

```
2026-09-30 - Wednesday 3h05
* 09:00 - Reviewed PR 15m [+review @rails]
```

The colors are the Ruby ones mapped onto the palette: the day in `red`, durations in `cyan`, the
text bold, `[+action @context]` in italic `comment`. They are baked into Rich text from
`BaseApp.palette`, so `FiniApp.apply_theme` repaints the list through `LogsView.set_colors`.

The logs are plain text: one `Static` (`#logs-text`) holding all of them, in `LogsScroll`, a
`VerticalScroll` that takes focus for `j`, `k`, the arrows, Page Up/Down, Home and End. There is no
cursor. Being plain text, the mouse selects it the way Textual selects any text, and `y` copies it
(tui-kit's `COPY_BINDING`). Do not turn it back into an `OptionList` or `DataTable`: neither
selects text well. Long lines wrap. Keep the text short: with all 3,000-odd logs of the real database
(about 0.8 s to lay out), selecting and scrolling did not work in the terminal, most likely
because the `Static` is laid out again on every refresh and a selection refreshes it on every mouse
move. Seven days is about 60 lines.

## Command line

`fini log` is the Ruby fini's command line, with `log` in front: `fini log <message>` logs it,
`fini log` shows today, `fini log -v N` the last N days (today included), `fini log -e [N]` edits
the last N days (1 by default). It has its own parser (`__main__.log_parser`, through
`parse_intermixed_args`, so `-v 2` may come after a message's words); argparse's subcommands do
not allow that. Like the Ruby fini, every command clears the screen first and colors its output
with the terminal's own ANSI colors (red day, cyan durations, bold text, grey italic
`[+action @context]`), but only when stdout is a terminal. The output is the same text the Logs
tab shows. Logging a message shows the day it was logged on.

A message (`message.parse_message`, a port of `message_parser.rb` and its spec in
`tests/test_message.py`) loses its first `@duration` (`@30m`, `@2h`, `@1.5h`, `@1h30`), then its
first `@context`, then its first `+action`; spaces left doubled are squeezed. An action or context
it does not give comes from the config's rules, tried in the file's order against the whole
message (`re.search`), else that setting's `default`. Run over the 3,098 logs of the real database,
the port gives the same text and duration for every one; the action or context differs for 84,
logged before the rules were last changed (`email` became `comm`).

`-e` writes the days as markdown to a temporary file (`log_command.render_markdown`), each log as
it was typed:

```
# 2026-09-30 - Wednesday
* 09:00 - Reviewed PR @15m
```

then runs `$EDITOR` (`vim` if unset) on it and, whatever the editor's exit status, reads it back
(`parse_markdown`): every day whose `# YYYY-MM-DD` header is still in the file has all its logs
deleted and replaced by the `* HH:MM - message` lines under it, parsed again with the current
rules, in one transaction (`logs.replace_days`). Other lines are ignored, and a day whose header
was removed keeps its logs. Times lose their seconds, as in the Ruby fini. A date or time that
does not exist saves nothing and keeps the file, whose path the error gives.

## Config

`~/.config/fini/config.yml` is optional. It is the file the Ruby fini read. `action` and `context`
each hold a `default` and `rules`, a name per list of regular expressions (`config._read_inference`;
a `null` or invalid pattern is skipped, the latter with a warning). `database_path` is the
SQLite file (`~` expanded), `~/.config/fini/fini.sqlite3` by default.
`theme` is `terminal` (the default) or the slug of a scheme in tui-kit; the picker writes it back
with `tui_kit.config.save_setting`, which changes only that line.
`config.example.yml` at the git root shows every key.

## Database

`database.open_database` opens the SQLite file with the standard library's `sqlite3` and runs
the migrations it lacks. `database.MIGRATIONS` is a list of SQL scripts, in order; `PRAGMA
user_version` is how many of them a database has run, and each runs with its new number in one
transaction. Add a migration at the end; never edit one that may have run.

Migration 1 is the `logs` table and its three indexes exactly as the Ruby fini's Sequel
migrations made them, read off a real database. A Ruby fini database is at `user_version` 0 with
a `logs` table already: it is marked as being at `RUBY_VERSION` and migration 1 never runs on it.
Its `schema_migrations` table (Sequel's) is left alone. Before the first change to a database
that existed, it is copied next to itself as `<name>.backup-v<version>.sqlite3`, once per version.

Timestamps (`logged_at`, `created_at`) are text in local time, `2026-09-30 15:14:26.000000`, the
format Sequel wrote; new rows must use it too, so sorting and date filters keep working.
`duration` is in minutes, NULL when the message gave none.

## Versions

The version comes from git tags via setuptools-scm. Tags have no `v` prefix. Release by tagging:
`git tag 0.1.0`.
