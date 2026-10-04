import argparse
import sys
from collections.abc import Sequence

from tui_kit.start import start

from . import __version__, log_command, note_command
from .app import TravailApp
from .config import load_config

LOG_EPILOG = """examples:
  travail log                              show today's logs
  travail log -v 7                         show the last 7 days' logs
  travail log -e                           edit today's logs
  travail log -e 3                         edit the last 3 days' logs
  travail log your message @2h @context    log a message with a duration and a context

message format:
  @<duration>   duration (examples: @30m, @1h, @1.5h, @1h45)
  @<context>    context (examples: @backend, @front-end)
  +<action>     action (examples: +meeting, +code)
  an action or context not given comes from the rules in ~/.config/travail/config.yml
"""


def days(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return number


def log_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="travail log",
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
    """travail note's parser, or travail todo's."""
    example = "Refactor the subscription model #rails" if kind == "todo" else "The staging password is in 1Password #work"
    parser = argparse.ArgumentParser(
        prog=f"travail {kind}",
        description=f"Write a {kind} without the TUI. #tags at the end go on their own line, after a blank one.",
        epilog=f'example:\n  travail {kind} "{example}"\n\nQuote it: the shell reads an unquoted #tag as a comment.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("message", nargs="+", help=f"the {kind}")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["log"]:
        # Its own parser: options may come after the message's words, which subcommands do not allow
        args = log_parser().parse_intermixed_args(argv[1:])
        raise SystemExit(log_command.run(load_config(), " ".join(args.message), view=args.view, edit=args.edit))
    if argv[:1] in (["note"], ["todo"]):
        kind = argv[0]
        args = note_parser(kind).parse_args(argv[1:])
        raise SystemExit(note_command.run(load_config(), " ".join(args.message), kind))

    parser = argparse.ArgumentParser(
        description="Todos, notes and a log of the work done, in the terminal.",
        epilog=(
            "travail log: log a message, or show or edit the logs, without the TUI (travail log --help); "
            "travail todo: write a todo (travail todo --help); travail note: write a note (travail note --help)"
        ),
    )
    parser.add_argument("--version", action="version", version=f"travail {__version__}")
    parser.parse_args(argv)
    start("travail", TravailApp)


if __name__ == "__main__":
    main()
