# Fini

Todos, notes and a log of the work done, in the terminal. All live in one local SQLite database.

## Installation

```bash
git clone <repo-url>
cd fini
./install.sh
```

## Usage

```bash
fini
fini --version
fini log Reviewed PR from Zach @20m     # log a message
fini log                                # today's logs
fini log -v 2                           # the last 2 days' logs
fini log -e 2                           # edit the last 2 days' logs in $EDITOR
fini todo "Refactor the subscriptions #rails"   # write a todo
fini note "Wifi password is on the fridge #home" # write a note
```

A message takes `@30m`, `@1h` or `@1h45` for the time spent, `@context` and `+action`; an action
or context it does not give comes from the rules in `~/.config/fini/config.yml`
(`config.example.yml` shows them). `fini log --help` lists it all.

`tab` switches between the Notes, Todos, Logs and Stats tabs. On Todos, `n` writes a new todo, Enter shows one
(Escape goes back), and `e` edits it in `$EDITOR` (empty it to delete it), `x` marks it done, `p` or space pins it, `f` shows
open, done or all todos (`is:open` or `is:done` in the search), `/` searches, and `#tag` in a todo's text makes a tag to filter on. Notes work the same, without done:
they can only be pinned or deleted, and a search can hold several tags. The Logs tab shows the last 7 days of logs, the last day first;
`j` and `k` scroll; select text with the mouse and press `y` to copy it. `?` lists every shortcut, `t` changes the theme
and `q` quits.

## Configuration

Nothing is required. `~/.config/fini/config.yml` holds the theme, which `t` writes:

```yaml
theme: one-light
```

`config.example.yml` shows every key.

## Development

```bash
uv run fini
uv run python -m unittest discover -s tests
uv run ruff check .
```

Releases are git tags without a `v` prefix (`0.1.0`); the version is derived from them by setuptools-scm.
