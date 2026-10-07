# Taf

TUI for todos, notes and a log of the work done ("taf" is French slang for "work"), all kept in one
local SQLite database. It was called fini until 0.6.1, then travail until 0.7.0, and replaces the Ruby fini CLI
(`git show 8dd3731^:lib/fini/models/log/message_parser.rb` for its message parser).

It is built on [tui-kit](../tui-kit), shared with outils, flotte and yafyaf-tui: the themes and the
picker (`t`), the messages, Help (`?`), the dialogs, the startup check and the
buttons' look (the `tinted` class) all come from there. Code that every app would use goes in
tui-kit, not here; see its AGENTS.md. Like outils, it has no title bar (tui-kit's `AppHeader`): the
tabs are the first row, and every message goes to the footer.

## Rules

- Do not git commit unless asked
- Help (`TafHelpScreen`, as in outils) lists the bindings that have a description and a `group`
  (`tui_kit.shortcuts.ACTIONS` or `GENERAL`): `TafApp.BINDINGS` on the left, under General, and
  on the right those the tab on show names in its `help_section()` (the Todos or Notes list's, a
  todo's or a note's while one is on show, the Logs' or the Stats'); document a new key there
- Never hardcode a color in a `.tcss` file

## Run

```bash
taf
taf log Reviewed PR from Zach @20m     # log a message
taf log                                # today's logs
taf log -v 2                           # the last 2 days' logs
taf log -e 2                           # edit the last 2 days' logs in $EDITOR
taf todo "Refactor the subscriptions #rails"   # write a todo
taf note "Wifi password is on the fridge #home" # write a note
```

`taf` refuses to start unless stdin and stdout are a terminal (tui-kit's `start`); `taf log`,
`taf todo` and `taf note` do not go through that check.

## Test

Run both from the git root.

```bash
uv run python -m unittest discover -s tests
uv run ruff check .
```

There is no pytest. App tests point `database_path` at a temporary file (`run_app` in
`tests/test_app.py`); a test that builds `TafApp` without one opens the user's real database.
`ruff` is pinned in the `dev` dependency group, so use `uv run ruff`.
tui-kit comes from GitHub's master (`[tool.uv.sources]`); after a push there,
`uv lock --upgrade-package tui-kit` picks it up. To work on both at once, switch that source to
the commented-out `../tui-kit` path.

## Structure

```
taf/                       # git root + pyproject.toml (run uv commands here)
  taf/                     # Python package
    __init__.py         # The version and the repository's URL
    __main__.py         # The command line: the TUI, or `taf log`'s own parser
    note_command.py     # `taf note` and `taf todo`: write one in the shell, tags at the end on their own line; no Textual
    log_command.py      # `taf log`: log, view and edit in the shell, as the Ruby fini did; no Textual
    message.py          # A message's @duration, @context and +action, and the rules that infer the rest; no Textual
    app.py              # TafApp, a tui-kit BaseApp: TABS, the footer and its messages, the keys
    config.py           # Optional ~/.config/taf/config.yml (theme, through tui_kit.config; database_path)
    database.py         # Opening the SQLite database and its migrations; no Textual
    editor.py           # edit_text: some text in $EDITOR through a temporary file; no Textual
    notes.py            # Note (a todo is a note of the kind todo), listing and searching, saving, done and pinned, #tags; no Textual
    logs.py             # Log, reading, creating and replacing logs, formatting a duration; no Textual
    stats.py            # The Stats tab's sums: time per day, action and month, periods, shades; no Textual
    screens/            # TafHelpScreen: Help with the app's keys and the tab's own, as in outils
    widgets/            # One view per tab: notes_tab.py, NotesTab and TodosTab (the list, notes_view.py, whose rows are
                        # notes_table.py, or one note, note_detail.py, in note_markdown.py), logs_view.py and stats_view.py;
                        # dashed_rule.py, the rule under the lists' count, copied from yafyaf-tui
    styles/taf.tcss     # taf's own styles, joined after tui-kit's (app.STYLE_FILES)
```

## Layout

The `#tabs` `TabbedContent` is the first row, one tab per entry in `TABS` (`app.py`): Notes,
then Todos, then Logs, then Stats; the app opens on Notes. Each pane is `<name>-tab` and holds its view, `<name>-view`. A click
on a tab or `tab` switches; `tab` is an app binding with `priority`, so the screen's own `tab`
(focus next) never runs, and it is skipped while a panel or dialog is up. The tabs cannot take
focus, so a view keeps its keys. `TafApp.tab` is the name of the tab on show. When a tab shows,
its view's `tab_shown` gives focus to its list. `AUTO_FOCUS`
is None: `TabbedContent` switches to the tab of whatever has focus, so Textual focusing the logs
list on start would open on Logs.

Under every tab, `#app-footer` is docked at the bottom: a rule (`border-top`) over a red Exit
button (tui-kit's `tinted -red`), which quits, on the left, and Help, which opens the shortcuts
like `?`, on the right (`dock: right`). Neither can take focus (`widgets.buttons.flat_button`), so a
click leaves the view's keys working. tui-kit shows messages in
whatever `HeaderNotification` the screen holds, so the footer holds one, `FooterMessage`: while a
message shows, it takes Help's place, right-aligned (an error wraps onto up to three lines), and
Help comes back once it clears. Copied from outils.

## Todos

Todos and notes are one table, `notes`, and one model, `notes.Note`: a todo is a note whose `kind`
is `todo` (`notes.TODO`), a plain note's is `note` (`notes.NOTE`). Every function in `notes.py`
takes the kind where it lists (`list_notes`, `tag_counts`); `set_done` leaves a plain note alone.
The widgets are the same too: `NotesTab`, `NotesView`, `NoteDetail` and `NotesTable` are for
notes, and `TodosTab`, `TodosView` and `TodoDetail` subclass them with `KIND = TODO`, adding the
status (see Notes for what differs). This section says "todo", but all of it holds for a note
unless Notes says otherwise.

The Todos tab is YafYaf's yaf list (yafyaf-tui's `YafsView`) on the local database, and the todos
YafYaf had for a while (kept in a stash in yafyaf-tui and yafyaf, "Todos tab" and "Todos API").
`TodosView` is a search box, the Tags dropdown, the status dropdown (Open, Done, All) and New
Todo, over the count in green ("2 open todos", "1 todo matching 'x'"), a dashed rule
(`DashedRule`) and `NotesTable`, which has no header. A row is the id in `$fg` (the table's color), a check box and a star (Nerd Font `󰄱`/`󰄲`, `☆`/`★`), then
the summary: the first line with text, links by their label in blue, inline
code without its backticks in orange (as in the view), a markdown heading without its `#`s in yellow, tags in purple, then the todo's tags that are not
in that first line (`Note.tags`, from the whole content) in cyan, clickable like the others;
all gray once done. The last updated first,
`updated_at` only (`notes.list_notes`): pinned and done todos are not sorted apart.

A todo is `content`, `tags`, `pinned`, `done_at` (done is `done_at` being set; marking a done
todo done again keeps the first time), `created_at` and `updated_at`. `tags` is a JSON array,
`["home", "work"]`, of the `#tags` in the content (YafYaf's rule, `notes.TAG`: a letter after the
`#`, not glued to what precedes it, never in inline code), rewritten on every save, so the Tags
dropdown's counts and a `#tag` in the search are SQL over `json_each`. The status is in the search, as on GitHub:
`is:open` (the search starts with it) or `is:done` (`is:closed` too), and none for all
(`notes.split_status`; the last one wins). The status dropdown only mirrors it: `TodosView.load`
sets the dropdown from the search, and picking a status, or `f`, puts `is:open` or `is:done` first
in the search in place of the one there, or takes it out for All. A search keeps the todos
that have every `#tag` (SQL) and whose content, its tags left out (`notes.without_tags`), has
every plain word, case ignored (in Python, as `LIKE` cannot leave the tags out; there are few
todos): "api" finds "the API" and "rapid", not "#api", which `#api` finds.

Keys, on the list: `n` (or New Todo) writes a new todo, Enter (or a click on a row) shows the
highlighted one, `e` or Shift+Enter edits it. `x` marks done or not, `p` or space pins or not, `f`
cycles Open, Done, All, `/` goes to the search (Enter runs it, Escape goes back), `#` opens Tags,
`r` reloads, `y` copies the todo. A click on the box marks done, on the star pins, by which half
of their column it hit, since Alacritty draws the Nerd Font box wider than its cell; a click
on a tag puts it in the search, on a link opens it. Picking a tag, by a click, in the view or from
the Tags dropdown, replaces any tag already in the search and keeps its words
(`TodosView.add_tag`): a todo has one tag at most, so two would find nothing. Like the
status dropdown, Tags mirrors the search: it shows the search's tag, or "Any tag", its first choice,
when there is none (or one no todo has); picking it takes the tag out of the search, as All takes
`is:` out. It has no blank "Tags" choice. Marking done and pinning change the box or the
star in the row and move nothing, which would be confusing: the status filter applies on the next
load (a todo marked done stays on the Open list, gray, until then). Neither changes `updated_at`, which
says when the content last changed.

`TodosTab` (`widgets/notes_tab.py`) is what the tab holds: the list (`TodosView`) or, in its
place, one todo (`TodoDetail`), as yafyaf-tui's `MainArea` switches between its list and
`YafDetail`; `NotesTab.viewing` is the todo on show, or None. The view shows a line first: the id,
"#12", then the check box and the star as in the list, which a click toggles (in the list's row too), then, in green,
"Updated Monday, July 1, 2026" (`notes.long_date`, yafyaf-tui's format), when the content last
changed; then its content as markdown (`NoteMarkdown`, a
copy of yafyaf-tui's `YafMarkdown`: links the terminal can open, tags that filter the list, code
blocks; its styles map Textual's markdown onto the palette). Escape or `q` goes back to the list,
`e` or Shift+Enter edits, `y` copies the selection or the todo, `j` and `k` scroll. At the right
end of the date's line are Close, back to the list like Escape, then a blue Edit and a red Delete
(which asks first, Cancel focused). While the list is on show, the footer has a green Refresh after
Exit, which reloads it like `r` (the tab's `reload`), for todos written by `taf todo` meanwhile;
it shows on Logs too, not on Stats (`TafApp.refresh_footer`, also run when the tab changes).

Editing (`NotesTab.edit`) opens the todo in `$EDITOR` (`editor.edit_text`, inside
`App.suspend`) as markdown under YAML front matter with `id`, `created_at`, `updated_at`, `done_at` (the
time, or nothing) and `pinned` (`true` or `false`), colons lined up (`notes.front_matter`,
`editor.field_lines`), like a yaf in yafyaf-tui's editor; a new todo opens empty. The front matter
is for the eye only: it is dropped on save (`editor.without_front_matter`), changed or not.
Emptied, a todo is deleted once confirmed, and a new one left empty is a cancel; an editor that
exits with an error (`:cq`) saves nothing. Saving goes back where the edit started: the todo,
showing what was saved, or the list, reloaded with the cursor on the todo. A todo deleted from its
view goes back to the list.

The id is the `notes` row's id, shown everywhere so that a todo can be referred to, by an agent
that implements it for one. Todos and notes share the table, so an id is unique across both, and
it stays the same if a note's kind changes.

## Notes

The Notes tab (`NotesTab`) is the Todos tab without the status: no check box in a row or in the
view (only the star, so its column is 1 wide, `notes_table.lead_width`), no status
dropdown, no `x` or `f`, no `is:` in the search (typed, it is ignored), no `done_at` in the
editor's front matter. Notes are pinned and deleted like todos. A note may have many tags, so
picking a tag (`NotesView.add_tag`) adds it to the search rather than replacing the one there, and
Any tag takes them all out; the Tags dropdown shows the search's last tag. `TodosView.add_tag`
keeps the todos' one tag. Both tabs share the footer's Refresh, which acts on the tab on show
(`TafApp.active_view`). The ids inside the two tabs are the same
(`#notes-list`, `#search`, `#note-detail`...), so a test scopes its queries to the tab
(`app.query_one("#todos-view")`); `AppCase.TAB` in `tests/test_notes_view.py` is the tab a test
starts on.

A `Select` sends `Changed` when mounted: `NotesView._tag_picked` ignores a pick of the tag
already in the search, or the Todos tab's list would take focus and the app would open on Todos.

## Logs

`TafApp` opens the database when built (`database.open_database`); when it cannot,
`TafApp.database` is None, the error shows in the footer and in place of the list
(`database_error`). `LogsView` shows a week of logs, Monday to Sunday, this week at first
(`LogsView.span`, `logs.logs_between`). The two rows over the dashed rule have, in their middle,
the week's days in blue ("Sep 28 to Oct 4, 2026") over its ISO number in yellow ("Week 40"), in a
box 26 wide (`#logs-period`) so the buttons never move, between Previous and Next, on the dates' row (grey, `tinted -plain`, not focusable, so the logs keep their keys; Next is
disabled on this week), or `[` and `]` (`LogsView.page`, weeks back from this one). The two sides
of the rows (`.logs-side`) are as wide, so the week stays centered with New Log on the right. With no logs, it says "No logs in week 38". Tests say which week is this one by patching
`logs_view.today` (`run_app` in `tests/test_app.py`: Thursday, October 1, 2026, with `LOGS`).
It shows them the way the Ruby fini's `TerminalPresenter` printed
them: the last day first, each day's logs in the order they were logged, under a header with the
day and the time spent on it all:

```
2026-09-30 - Wednesday 3h05
* 09:00 - Reviewed PR 15m [+review @rails]
```

The colors are the Ruby ones mapped onto the palette: the day in `red`, durations in `cyan`, the
text bold, `[+action @context]` in italic `comment`. They are baked into Rich text from
`BaseApp.palette`, so `TafApp.apply_theme` repaints the list through `LogsView.set_colors`.

The logs are plain text: one `Static` (`#logs-text`) holding all of them, in `LogsScroll`, a
`VerticalScroll` that takes focus for `j`, `k`, the arrows, Page Up/Down, Home and End. There is no
cursor. Being plain text, the mouse selects it the way Textual selects any text, and `y` copies it
(tui-kit's `COPY_BINDING`). Do not turn it back into an `OptionList` or `DataTable`: neither
selects text well. Long lines wrap. Keep the text short: with all 3,000-odd logs of the real database
(about 0.8 s to lay out), selecting and scrolling did not work in the terminal, most likely
because the `Static` is laid out again on every refresh and a selection refreshes it on every mouse
move. A week is about 60 lines, which is why the tab pages by week rather than show more.
`LogsScroll` stays shown with no logs (the "No logs" text is inside it), so it keeps focus and
the tab's keys.

At the right end of the dates' row, a blue New Log button (or `n`) opens `NewLogScreen`, a wide
window (90% of the screen, 140 at most) with a box that logs the message on Enter or Log, as
`taf log` does (`logs.create_log` with the config's rules), then closes and shows this week
again; Escape or Cancel closes it without logging. Under the box, `#log-preview` shows the message
as it will be stored, parsed again on every key (`message.parse_message`): "Met Bob @2" shows a
context `@2` until the `0m` makes it a duration. A database error shows there, in red, and the
window stays open with the message.

A click on a day's date (red, underlined under the mouse, an `@click` on `LogsText`) edits that
day; `e` edits the last day with logs on show, or, with none, today in this week and the Sunday in another. A drag
that selects text and ends on a date does not edit (`LogsText.action_edit_day` checks for a
selection). The day opens alone in `$EDITOR` (`LogsView.edit_day`), in `taf log -e`'s markdown
(`log_command.render_markdown`, given the day so an empty one still gets its header to write
under), through `editor.edit_text` inside `App.suspend` as notes
are edited. Once the file is written (`:w`), even unchanged, the day is replaced (`parse_markdown`,
`logs.replace_days`), so its logs are read again with the config's current rules; quitting without
writing (`:q`, told apart by the file's mtime, `editor.edit_written_text`) or an editor that exits
with an error saves nothing. Another day's header with entries
under it adds that day too, when it has no logs yet; a day that has logs saves nothing and keeps
the edit, as its logs were never in the file, and so does a file without the day's own header. Emptying the day under its header deletes its logs without asking, as `-e` does. A date or
time that does not exist, a broken log line, or a database error (say, locked by `taf log -e`)
saves nothing and keeps the edit in a file whose path the error gives. `r`, or the footer's
green Refresh (shown on Logs too), reads the days again, for logs written by `taf log` meanwhile.

## Stats

`StatsView` (`widgets/stats_view.py`) shows where the time went, for a period and all actions or
one. Two dropdowns pick them: Period (`stats.periods`: the last 12 months, each year, the last
first, then All time, a graph per year) and Action ("All actions", then the period's actions, the
most time first, with their hours, `meet (268 h)`); a period without the action picked goes back
to All actions. A third, Show, is Hours or Percentages: Percentages hides every hour, to share
the screen (the figures become the first actions' shares, the months 100% bars of each month's
shares, or the action's share of each month). Show is saved as `stats_show` in the config, through
`Config.path`, which tests point at a temporary file. The dropdowns have no keys. Under them, plain Rich text in `StatsScroll`, like the Logs tab
(selectable, `y` copies): a line of figures, a GitHub-like graph of the days (a column per week, a
row per weekday, Monday first; four shades of green blended into `bg`, by the quartiles of the days
with time, `stats.levels`), the share of time per action as bars, and a bar per month, its actions
stacked, then a line chart over the months (`month_chart`, drawn in braille dots by `BrailleGrid`, 2
dots by 4 a cell; `CHART_MONTH_WIDTH` cells a month, `CHART_HEIGHT` rows): one line per action
for the first `CHART_ACTIONS` (3), the most time in the period first, all on one scale (hours, or
shares of each month), rounded up to 10; the action picked alone. More lines crowd the bottom. A cell has one color: where
lines cross, the first action's wins. One scale on purpose: rows each to their own scale made a
small action's peak look as big as code's. Each action has a color by its rank in the period (`ACTION_COLORS`). One action narrows
the figures, the graph and the months to it; the action bars stay whole, the others gray. A pick
gives focus back to the text; a `Select` also sends `Changed` when mounted, so only a pick by a
focused dropdown does, or the app would open on Stats.

Every log with a duration counts, except `+pto` (`stats.TIME_OFF`). A day with a `+pto` log
and no other log with a duration (`stats.time_off_days`) is blue in the graph, whatever the
action picked, with "Time off" in the legend. A US federal holiday with no log with a duration
(`stats.holidays_off`, through the `holidays` package, as in outils) is red, whatever the action
picked, with "Holiday" in the legend, even with a `+pto` log. The logs are read again
(`stats.load_entries`, all in memory, about 3,000 rows) each time the tab shows. The graph is about 110 columns wide; a narrower terminal scrolls it sideways.

## Command line

`taf log` is the Ruby fini's command line, with `log` in front: `taf log <message>` logs it,
`taf log` shows today, `taf log -v N` the last N days (today included), `taf log -e [N]` edits
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
was removed keeps its logs. A log with no message (`* 11:00 -`) is kept. Times lose their
seconds, as in the Ruby fini. A date or time that does not exist, or a line under a day that
starts with `* ` or looks like a mistyped or reformatted log (`* 9:00 - x`, `- 09:00 - x`,
indented; `ENTRY_LIKE`), which its day would lose, saves nothing and keeps the file, whose path
the error gives. A COMMIT that fails (a locked database) is rolled back, so no transaction stays
open.

`taf todo <message>` writes a todo, and `taf note <message>` a note (`note_command.run`, their
own parser, `__main__.note_parser`). The `#tags` at the end of the message go on their own line
after a blank one (`note_command.note_content`): `taf todo "Refactor the subscriptions #rails"` stores
`Refactor the subscriptions\n\n#rails`, so the list shows the text with `#rails` in cyan after it,
and prints `Todo 12 created: ...` with the new id.
A tag inside the message stays where it is, and a message of tags only is kept as is. The message
must be quoted when it has a tag: the shell reads an unquoted `#rails` as a comment.

## Config

`~/.config/taf/config.yml` is optional. It is the file the Ruby fini read. `action` and `context`
each hold a `default` and `rules`, a name per list of regular expressions (`config._read_inference`;
a `null` or invalid pattern is skipped, the latter with a warning). `database_path` is the
SQLite file (`~` expanded), `~/.config/taf/taf.sqlite3` by default.
`stats_show` is `hours` (the default) or `percentages`, set from the Stats tab.
`theme` is `terminal` (the default) or the slug of a scheme in tui-kit; the picker writes it back
with `tui_kit.config.save_setting`, which changes only that line.
`config.example.yml` at the git root shows every key.

## Database

`database.open_database` opens the SQLite file with the standard library's `sqlite3` and runs
the migrations it lacks. `database.MIGRATIONS` is a list of SQL scripts, in order; `PRAGMA
user_version` is how many of them a database has run, and each runs with its new number in one
transaction. Add a migration at the end; never edit one that may have run.

Migration 2 adds the `todos` table; migration 3 renames it `notes` and adds `kind`, every row
before it being a todo (see Todos). Migration 1 is the `logs` table and its three indexes exactly as the Ruby fini's Sequel
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
