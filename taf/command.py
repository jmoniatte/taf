"""What taf's shell commands share: opening the database and printing an error; no Textual."""

import sqlite3
import sys

from .config import Config
from .database import open_database

RED = "\033[31m"
RESET = "\033[0m"


def print_error(message: str, color: bool = False) -> None:
    print(f"{RED}{message}{RESET}" if color else message, file=sys.stderr)


def open_for_command(config: Config, color: bool = False) -> sqlite3.Connection | None:
    """Print the config's warnings, then open the database; None, once said why, when it cannot."""
    for warning in config.warnings:
        print(warning, file=sys.stderr)
    try:
        return open_database(config.database_path)
    except (sqlite3.Error, OSError) as error:
        print_error(f"Database Error: cannot open {config.database_path}: {error}", color)
        return None
