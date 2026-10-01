import argparse
import sys
from collections.abc import Sequence

from tui_kit.start import start

from . import __version__, log_command
from .app import FiniApp
from .config import load_config

LOG_EPILOG = """examples:
  fini log                              show today's logs
  fini log -v 7                         show the last 7 days' logs
  fini log -e                           edit today's logs
  fini log -e 3                         edit the last 3 days' logs
  fini log your message @2h @context    log a message with a duration and a context

message format:
  @<duration>   duration (examples: @30m, @1h, @1.5h, @1h45)
  @<context>    context (examples: @backend, @front-end)
  +<action>     action (examples: +meeting, +code)
  an action or context not given comes from the rules in ~/.config/fini/config.yml
"""


def days(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return number


def log_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fini log",
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


def main(argv: Sequence[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["log"]:
        # Its own parser: options may come after the message's words, which subcommands do not allow
        args = log_parser().parse_intermixed_args(argv[1:])
        raise SystemExit(log_command.run(load_config(), " ".join(args.message), view=args.view, edit=args.edit))

    parser = argparse.ArgumentParser(
        description="Todos and a log of the work done, in the terminal.",
        epilog="fini log: log a message, or show or edit the logs, without the TUI (fini log --help)",
    )
    parser.add_argument("--version", action="version", version=f"fini {__version__}")
    parser.parse_args(argv)
    start("fini", FiniApp)


if __name__ == "__main__":
    main()
