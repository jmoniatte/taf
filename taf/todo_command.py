"""`taf todo`: write a todo (through note_command), or list, show, close and reopen them, from
the shell, for the user and agents. No Textual."""

import argparse
import sqlite3
import sys
from contextlib import closing
from typing import TextIO

from . import note_command
from .command import open_for_command, print_error
from .config import Config, load_config
from .notes import TODO, Note, extra_tags, get_note, heading_text, list_notes, set_done

COMMANDS = ("list", "show", "done", "reopen")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="taf todo", description='Your todos. taf todo "text" writes one (taf todo --help).')
    sub = p.add_subparsers(dest="command", required=True)
    ls = sub.add_parser("list", help="open todos, the last updated first")
    status = ls.add_mutually_exclusive_group()
    status.add_argument("--done", dest="status", action="store_const", const="done", help="done ones only")
    status.add_argument("--all", dest="status", action="store_const", const="all", help="open and done")
    ls.add_argument("words", nargs="*", help="words and #tags the todo must have")
    ls.set_defaults(status="open")
    show = sub.add_parser("show", help="one todo in full")
    show.add_argument("id", type=int)
    for name in ("done", "reopen"):
        cmd = sub.add_parser(name, help=f"mark todos {'done' if name == 'done' else 'not done'}")
        cmd.add_argument("ids", nargs="+", type=int)
    return p


def write_parser() -> argparse.ArgumentParser:
    p = note_command.parser(TODO)
    p.epilog += "\n\ntaf todo list|show|done|reopen: your todos (taf todo list --help); taf todo alone lists the open ones"
    return p


def main(argv: list[str], config: Config | None = None, out: TextIO = sys.stdout) -> int:
    """taf todo: alone, the open todos; a first word in COMMANDS runs that command, anything else
    is a todo to write (quote a todo that starts with one of them, or start it differently)."""
    argv = argv or ["list"]
    if argv[0] not in COMMANDS:
        args = write_parser().parse_args(argv)
        return note_command.run(config or load_config(), " ".join(args.message), TODO, out)
    args = parser().parse_args(argv)
    connection = open_for_command(config or load_config())
    if connection is None:
        return 1
    with closing(connection):
        try:
            return run(connection, args, out)
        except sqlite3.Error as error:
            print_error(f"Database Error: {error}")
            return 1


def run(connection: sqlite3.Connection, args: argparse.Namespace, out: TextIO) -> int:
    if args.command == "list":
        for todo in list_notes(connection, TODO, " ".join(args.words), args.status):
            out.write(line(todo) + "\n")
        return 0
    if args.command == "show":
        todo = todo_or_none(connection, args.id)
        if todo is None:
            return 1
        out.write(line(todo) + "\n\n" + todo.content + "\n")
        return 0
    missing = [todo_id for todo_id in args.ids if todo_or_none(connection, todo_id) is None]
    for todo_id in args.ids:
        if todo_id not in missing:
            set_done(connection, todo_id, args.command == "done")
    return 1 if missing else 0


def todo_or_none(connection: sqlite3.Connection, todo_id: int) -> Note | None:
    note = get_note(connection, todo_id)
    if note is None or not note.is_todo:
        print(f"taf todo: no todo {todo_id}", file=sys.stderr)
        return None
    return note


def line(todo: Note) -> str:
    """#12 [x] The summary #tag, with the tags not in the summary and a star when pinned."""
    tags = " ".join(f"#{name}" for name in extra_tags(todo))
    parts = [f"#{todo.id}", "[x]" if todo.done else "[ ]", heading_text(todo.summary), tags, "★" if todo.pinned else ""]
    return " ".join(part for part in parts if part)
