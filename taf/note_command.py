"""Writing a note or a todo from the shell without the TUI: `taf note`, and `taf todo "text"` for
todo_command; no Textual."""

import argparse
import sqlite3
import sys
from typing import TextIO

from .command import open_for_command, print_error
from .config import Config
from .notes import NOTE, TAG, create_note, extra_tags


def parser(kind: str) -> argparse.ArgumentParser:
    """taf note's parser, or the one taf todo uses to write a todo."""
    example = "Refactor the subscription model #rails" if kind == "todo" else "The staging password is in 1Password #work"
    p = argparse.ArgumentParser(
        prog=f"taf {kind}",
        description=f"Write a {kind} without the TUI. #tags at the end go on their own line, after a blank one.",
        epilog=f'example:\n  taf {kind} "{example}"\n\nQuote it: the shell reads an unquoted #tag as a comment.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("message", nargs="+", help=f"the {kind}")
    return p


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
    connection = open_for_command(config)
    if connection is None:
        return 1
    try:
        note = create_note(connection, content, kind)
    except sqlite3.Error as error:
        print_error(f"Database Error: {error}")
        return 1
    finally:
        connection.close()
    tags = " ".join(f"#{name}" for name in extra_tags(note))
    out.write(f"{kind.capitalize()} {note.id} created: {note.summary}" + (f" ({tags})" if tags else "") + "\n")
    return 0
