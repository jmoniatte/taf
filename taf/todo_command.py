"""`taf todo list`, `show`, `done` and `reopen`: the todos from the shell, for the user and agents;
`taf todo "text"` itself is note_command's. No Textual."""

import argparse
import re
import sqlite3
import sys
from contextlib import closing
from typing import TextIO

from .config import Config
from .database import open_database
from .notes import TODO, Note, get_note, list_notes, set_done

COMMANDS = ("list", "show", "done", "reopen")
# A markdown heading's marks, left out of the line
HEADING = re.compile(r"^#{1,6}\s+")


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


def main(config: Config, argv: list[str], out: TextIO = sys.stdout) -> int:
    args = parser().parse_args(argv)
    try:
        connection = open_database(config.database_path)
    except (sqlite3.Error, OSError) as error:
        print(f"Database Error: cannot open {config.database_path}: {error}", file=sys.stderr)
        return 1
    with closing(connection):
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
    tags = " ".join(f"#{name}" for name in todo.tags if f"#{name}" not in todo.summary.lower())
    parts = [f"#{todo.id}", "[x]" if todo.done else "[ ]", HEADING.sub("", todo.summary), tags, "★" if todo.pinned else ""]
    return " ".join(part for part in parts if part)
