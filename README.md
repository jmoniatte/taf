# Travail

Todos, notes and a log of the work done, in the terminal. All live in one local SQLite database.
It was called fini until version 0.6.1.

## Installation

```bash
git clone git@github.com:jmoniatte/travail.git
cd travail
./install.sh
```

Coming from fini: run `uv tool uninstall fini`, then move `~/.config/fini` to `~/.config/travail`.
If you had no `database_path` in the config, also rename `fini.sqlite3` there to `travail.sqlite3`.

## Usage

```bash
travail
travail --version
travail log Reviewed PR from Zach @20m     # log a message
travail log                                # today's logs
travail log -v 2                           # the last 2 days' logs
travail log -e 2                           # edit the last 2 days' logs in $EDITOR
travail todo "Refactor the subscriptions #rails"   # write a todo
travail note "Wifi password is on the fridge #home" # write a note
```

A message takes `@30m`, `@1h` or `@1h45` for the time spent, `@context` and `+action`; an action
or context it does not give comes from the rules in `~/.config/travail/config.yml`
(`config.example.yml` shows them). `travail log --help` lists it all.

`tab` switches between the Notes, Todos, Logs and Stats tabs. `?` lists every shortcut, `t` changes
the theme and `q` quits.

- **Todos**: `n` writes a new todo, Enter shows one (Escape goes back), `e` edits it in `$EDITOR`
  (empty it to delete it), `x` marks it done, `p` or space pins it, `f` shows open, done or all
  todos (`is:open` or `is:done` in the search), `/` searches, and `#tag` in a todo's text makes a
  tag to filter on.
- **Notes**: the same as todos, without done. A search can hold several tags.
- **Logs**: one week at a time, the last day first. `[` and `]` go to the previous and next week,
  `n` logs a new message, and `e` or a click on a day's date edits that day in `$EDITOR`. `j` and
  `k` scroll; select text with the mouse and press `y` to copy it.
- **Stats**: where the time went, for a period and one action or all: a graph of the days, the
  share of each action, and the hours per month. Days off and US holidays show in their own color.

## Configuration

Nothing is required. `~/.config/travail/config.yml` can hold:

```yaml
theme: one-light                 # written by `t`
database_path: '~/logs.sqlite3'  # ~/.config/travail/travail.sqlite3 by default
stats_show: percentages          # or hours, set from the Stats tab
```

`config.example.yml` shows every key, including the action and context rules.

## Development

```bash
uv run travail
uv run python -m unittest discover -s tests
uv run ruff check .
```

Releases are git tags without a `v` prefix (`0.1.0`); the version is derived from them by setuptools-scm.
