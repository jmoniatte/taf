# Fini

Todos and a log of the work done, in the terminal. Both live in one local SQLite database.

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
```

`tab` switches between the Todos and Logs tabs. The Logs tab shows the last 7 days of logs, the last day first;
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
