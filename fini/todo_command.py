"""`fini todo`: write a todo from the shell without the TUI; no Textual."""

import sqlite3
import sys
from typing import TextIO

from .config import Config
from .database import open_database
from .todos import TAG, create_todo


def todo_content(message: str) -> str:
    """The message, with the #tags at its end moved under it after a blank line:

    "Refactor the subscriptions #rails" -> "Refactor the subscriptions\\n\\n#rails"

    A tag inside the message stays where it is.
    """
    words = message.split()
    split = len(words)
    while split > 0 and TAG.fullmatch(words[split - 1]):
        split -= 1
    text, tags = " ".join(words[:split]), " ".join(words[split:])
    if not text or not tags:
        return " ".join(words)
    return f"{text}\n\n{tags}"


def run(config: Config, message: str, out: TextIO = sys.stdout) -> int:
    """Store the message as a new todo; returns the exit code."""
    content = todo_content(message)
    if not content:
        print('Nothing to save: fini todo "Your todo #tag"', file=sys.stderr)
        return 2
    for warning in config.warnings:
        print(warning, file=sys.stderr)
    try:
        connection = open_database(config.database_path)
    except (sqlite3.Error, OSError) as error:
        print(f"Database Error: cannot open {config.database_path}: {error}", file=sys.stderr)
        return 1
    try:
        todo = create_todo(connection, content)
    finally:
        connection.close()
    tags = " ".join(f"#{name}" for name in todo.tags)
    out.write(f"Todo created: {todo.summary}" + (f" ({tags})" if tags and tags not in todo.summary else "") + "\n")
    return 0
