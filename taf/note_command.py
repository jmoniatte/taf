"""`taf note` and `taf todo`: write a note or a todo from the shell without the TUI; no Textual."""

import sqlite3
import sys
from typing import TextIO

from .config import Config
from .database import open_database
from .notes import NOTE, TAG, create_note


def note_content(message: str) -> str:
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


def run(config: Config, message: str, kind: str = NOTE, out: TextIO = sys.stdout) -> int:
    """Store the message as a new note of the kind; returns the exit code."""
    content = note_content(message)
    if not content:
        print(f'Nothing to save: taf {kind} "Your {kind} #tag"', file=sys.stderr)
        return 2
    for warning in config.warnings:
        print(warning, file=sys.stderr)
    try:
        connection = open_database(config.database_path)
    except (sqlite3.Error, OSError) as error:
        print(f"Database Error: cannot open {config.database_path}: {error}", file=sys.stderr)
        return 1
    try:
        note = create_note(connection, content, kind)
    finally:
        connection.close()
    tags = " ".join(f"#{name}" for name in note.tags)
    out.write(f"{kind.capitalize()} {note.id} created: {note.summary}" + (f" ({tags})" if tags and tags not in note.summary else "") + "\n")
    return 0
