# Taf

Todos, notes, a log of the work done, and what needs you from Slack and GitHub (the watch), in the
terminal. All live in one local SQLite database.
It was called fini until version 0.6.1, then travail until 0.7.0.

## Installation

```bash
git clone git@github.com:jmoniatte/taf.git
cd taf
./install.sh
```

Coming from travail: run `uv tool uninstall travail`, then move `~/.config/travail` to `~/.config/taf`.
If you had no `database_path` in the config, also rename `travail.sqlite3` there to `taf.sqlite3`.

## Usage

```bash
taf
taf --version
taf log Reviewed PR from Zach @20m     # log a message
taf log                                # today's logs
taf log -v 2                           # the last 2 days' logs
taf log -e 2                           # edit the last 2 days' logs in $EDITOR
taf todo "Refactor the subscriptions #rails"   # write a todo
taf todo                               # the open todos (taf todo list --all, --done, #tag)
taf todo done 12                       # also: show, reopen
taf note "Wifi password is on the fridge #home" # write a note
taf watch                              # what needs you, by project
taf watch --help                       # add, list, search, show, done, reopen, pin, project...
```

A message takes `@30m`, `@1h` or `@1h45` for the time spent, `@context` and `+action`; an action
or context it does not give comes from the rules in `~/.config/taf/config.yml`
(`config.example.yml` shows them). `taf log --help` lists it all.

`tab` switches between the Watch, Todos, Notes, Logs and Stats tabs (the app opens on Watch). `?` lists every shortcut, `t` changes
the theme and `q` quits.

- **Todos**: `n` writes a new todo, Enter shows one (Escape goes back), `e` edits it in `$EDITOR`
  (empty it to delete it), `x` marks it done, `p` or space pins it, `f` shows open, done or all
  todos (`is:open` or `is:done` in the search), `/` searches, and `#tag` in a todo's text makes a
  tag to filter on.
- **Notes**: the same as todos, without done. A search can hold several tags.
- **Watch**: what needs you. The pull requests waiting on your review come first, under Pull
  Requests, with how many PRs are ready to deploy (`deploy_repo` in the config) as a link; the
  rest is under a heading per project: Slack threads, replies on your pull requests, failing CI,
  and items agents added. `x` closes one, `p` or
  space stars it, a click on its icon opens it in Slack or GitHub (failing CI has two: the build and the PR), Enter shows it in full, `f` shows open, done or
  all. The list reloads every minute. `c`, or the Collect button, collects now, as the timer does
  (GitHub, then Slack, a paid Claude run).
- **Logs**: one week at a time, the last day first. `[` and `]` go to the previous and next week,
  `n` logs a new message, and `e` or a click on a day's date edits that day in `$EDITOR`. `j` and
  `k` scroll; select text with the mouse and press `y` to copy it.
- **Stats**: where the time went, for a period and one action or all: a graph of the days, the
  share of each action, and the hours per month. Days off and US holidays show in their own color.

## Watch

A timer runs `taf watch collect`. It first reads GitHub with `gh` (no cost): your open pull
requests, what others said on them since you last replied, their failing checks, and the pull
requests waiting on your review or on one of your teams'. Then a headless Claude run (Sonnet unless
the config says otherwise) reads new Slack messages through the claude.ai Slack connector, with
read-only tools, and keeps only the conversations that matter to you. Raw messages are never stored. GitHub items close
by themselves once the PR is merged, CI passes, you reply, or the review is done.

### Setting it up

taf never holds a token of its own: it borrows the GitHub CLI's login, and Claude Code's.

1. **GitHub**, through the GitHub CLI. Install `gh`, then run `gh auth login` (GitHub.com, a browser
   login). The token needs the `repo` scope, to read private repos' pull requests and checks, and
   `read:org`, for review requests made to your teams; `gh auth login` gives both. Check with
   `gh auth status`, then `taf watch collect github`, which is free and prints your open PRs.
2. **Slack**, through Claude Code and claude.ai. Install Claude Code (`claude`), run it once and log
   in with `/login` using your claude.ai account (the connectors belong to the account; an API key
   alone has none). On claude.ai, under Settings, Connectors, connect **Slack** and allow it on your
   workspace. Claude Code finds the account's connectors on its own: `claude mcp list` should show
   `claude.ai Slack: https://mcp.slack.com/mcp - ✔ Connected`. The collector's Claude runs only
   get Slack's read tools (`taf/watch/slack.py`), so they can never post.
3. **Settings**: the `watch:` section of `~/.config/taf/config.yml` (`config.example.yml` shows it):
   the model (`haiku` is cheap and enough), the channels to skip, your review teams, the accounts to
   ignore, and the repo whose ready-to-deploy PRs to count.
4. **Try it**: `taf watch collect` reads GitHub, then Slack. The first Slack run reads the last 24
   hours (`first_run_hours`); later runs go on from where the last one stopped. `taf watch runs`
   shows each run, its cost and any error.
5. **The timer**: copy the two files below to `~/.config/systemd/user/`, then run
   `systemctl --user daemon-reload` and `systemctl --user enable --now taf-watch.timer`.
   `systemctl --user list-timers` shows the next run. After a change to the timer, run
   `systemctl --user daemon-reload` and `systemctl --user restart taf-watch.timer`.
   The service finds `taf`, `gh` and `claude` through its `PATH` line: add their folder there if
   they are installed elsewhere than `~/.local/bin`, `/usr/local/bin` or `/usr/bin`.

Run the timer on one machine only. With the database in a synced folder (Dropbox), two timers
would read Slack twice, pay twice, and write to the same file at once.

A systemd user timer, every 5 minutes from 8:00 to 22:00 on weekdays:

```ini
# ~/.config/systemd/user/taf-watch.service
[Service]
Type=oneshot
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=%h/.local/bin/taf watch collect
TimeoutStartSec=20min

# ~/.config/systemd/user/taf-watch.timer
[Timer]
OnCalendar=Mon..Fri *-*-* 08..21:00/5
OnCalendar=Mon..Fri *-*-* 22:00
RandomizedDelaySec=30

[Install]
WantedBy=timers.target
```

A project is a piece of work like `follow-privacy-levels`, not a repo. Each of your open pull
requests gives one, named after its branch; the Slack run files items under projects by channel,
PR or subject. Coding agents read the current branch's project with `taf watch context`, and add
items with `taf watch add`. Watch was veille, a separate tool, before it moved into taf.

## Configuration

Nothing is required. `~/.config/taf/config.yml` can hold:

```yaml
theme: one-light                 # written by `t`
database_path: '~/logs.sqlite3'  # ~/.config/taf/taf.sqlite3 by default
stats_show: percentages          # or hours, set from the Stats tab
watch:                           # the collectors' settings
  slack:
    skip_channels: [dev-notify]
  github:
    review_teams: [org/team]
```

`config.example.yml` shows every key, including the action and context rules and the watch's.

## Development

```bash
uv run taf
uv run python -m unittest discover -s tests
uv run ruff check .
```

Releases are git tags without a `v` prefix (`0.1.0`); the version is derived from them by setuptools-scm.
