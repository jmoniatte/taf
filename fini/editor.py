"""Editing text in the user's $EDITOR through a temporary file; no Textual."""

import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path

# The Ruby fini's default
DEFAULT_EDITOR = "vim"
FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)^---[ \t]*(?:\r?\n|\Z)", re.DOTALL | re.MULTILINE)


class EditorError(Exception):
    """The editor could not be started or did not exit cleanly."""


def editor_command() -> list[str]:
    # May carry arguments, e.g. "code --wait"
    return shlex.split(os.environ.get("EDITOR") or DEFAULT_EDITOR)


def edit_text(text: str, prefix: str) -> str:
    """Open text in $EDITOR and return it as saved, without its surrounding blank lines.

    EditorError when the editor cannot start or exits with an error (:cq in vim), so nothing is saved.
    """
    fd, name = tempfile.mkstemp(prefix=prefix, suffix=".md")
    path = Path(name)
    try:
        with open(fd, "w", encoding="utf-8") as file:
            file.write(text)
        command = [*editor_command(), str(path)]
        try:
            result = subprocess.run(command)
        except OSError as error:
            raise EditorError(f"Cannot start {command[0]}: {error.strerror or error}") from None
        if result.returncode != 0:
            raise EditorError(f"{command[0]} exited with status {result.returncode}, nothing was saved")
        return path.read_text(encoding="utf-8").strip("\r\n")
    finally:
        path.unlink(missing_ok=True)


def field_lines(fields: dict[str, str]) -> str:
    """One "key : value" line per field, the colons lined up."""
    width = max(map(len, fields), default=0)
    return "".join(f"{key:<{width}} : {value}".rstrip() + "\n" for key, value in fields.items())


def with_front_matter(fields: dict[str, str], body: str) -> str:
    """body under YAML front matter holding fields, like a yaf in YafYaf's editor."""
    return f"---\n{field_lines(fields)}---\n\n{body}"


def without_front_matter(text: str) -> str:
    """text without the front matter at its top, if any, and without the blank lines around it."""
    match = FRONT_MATTER.match(text)
    return (text[match.end() :] if match else text).strip("\r\n")
