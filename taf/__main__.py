import argparse
import sys
from collections.abc import Sequence

from . import __version__, log_command, note_command, todo_command
from .config import load_config

LOG_EPILOG = """examples:
  taf log                              show today's logs
  taf log -v 7                         show the last 7 days' logs
  taf log -e                           edit today's logs
  taf log -e 3                         edit the last 3 days' logs
  taf log your message @2h @context    log a message with a duration and a context

message format:
  @<duration>   duration (examples: @30m, @1h, @1.5h, @1h45)
  @<context>    context (examples: @backend, @front-end)
  +<action>     action (examples: +meeting, +code)
  an action or context not given comes from the rules in ~/.config/taf/config.yml
"""


def start(name: str, app: type) -> None:
    """tui-kit's start, loaded only to start the TUI: it brings Textual, which the commands never load,
    so the agent hooks' taf watch context stays quick."""
    from tui_kit.start import start as start_tui

    start_tui(name, app)


def days(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return number


def log_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="taf log",
        description="Log a message, or show or edit the logs of the last days, without the TUI.",
        epilog=LOG_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("-v", "--view", type=days, metavar="DAYS", help="view the logs of the last DAYS days")
    modes.add_argument(
        "-e", "--edit", type=days, nargs="?", const=1, metavar="DAYS", help="edit the logs of the last DAYS days (default: 1) in $EDITOR"
    )
    parser.add_argument("message", nargs="*", help="the message to log")
    return parser


def note_parser(kind: str) -> argparse.ArgumentParser:
    """taf note's parser, or taf todo's."""
    example = "Refactor the subscription model #rails" if kind == "todo" else "The staging password is in 1Password #work"
    parser = argparse.ArgumentParser(
        prog=f"taf {kind}",
        description=f"Write a {kind} without the TUI. #tags at the end go on their own line, after a blank one.",
        epilog=f'example:\n  taf {kind} "{example}"\n\nQuote it: the shell reads an unquoted #tag as a comment.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("message", nargs="+", help=f"the {kind}")
    if kind == "todo":
        parser.epilog += "\n\ntaf todo list|show|done|reopen: your todos (taf todo list --help); taf todo alone lists the open ones"
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["log"]:
        # Its own parser: options may come after the message's words, which subcommands do not allow
        args = log_parser().parse_intermixed_args(argv[1:])
        raise SystemExit(log_command.run(load_config(), " ".join(args.message), view=args.view, edit=args.edit))
    if argv[:1] in (["todo"], ["todos"]):
        rest = argv[1:] or ["list"]
        # A todo whose first word is one of these runs it: quote the todo or start it differently
        if rest[0] in todo_command.COMMANDS:
            raise SystemExit(todo_command.main(load_config(), rest))
        args = note_parser("todo").parse_args(rest)
        raise SystemExit(note_command.run(load_config(), " ".join(args.message), "todo"))
    if argv[:1] == ["note"]:
        args = note_parser("note").parse_args(argv[1:])
        raise SystemExit(note_command.run(load_config(), " ".join(args.message), "note"))
    if argv[:1] in (["watch"], ["watches"]):
        from .watch import cli

        raise SystemExit(cli.main(argv[1:]))

    parser = argparse.ArgumentParser(
        description="Todos, notes and a log of the work done, in the terminal.",
        epilog=(
            "taf log: log a message, or show or edit the logs, without the TUI (taf log --help); "
            "taf todo: write, list and close todos (taf todo --help); taf note: write a note (taf note --help); "
            "taf watch: what needs you from Slack and GitHub (taf watch --help)"
        ),
    )
    parser.add_argument("--version", action="version", version=f"taf {__version__}")
    parser.parse_args(argv)
    # Only here: the commands above never load Textual
    from .app import TafApp

    start("taf", TafApp)


if __name__ == "__main__":
    main()
