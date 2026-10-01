import argparse
from collections.abc import Sequence

from tui_kit.start import start

from . import __version__
from .app import FiniApp


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Todos and a log of the work done, in the terminal.")
    parser.add_argument("--version", action="version", version=f"fini {__version__}")
    parser.parse_args(argv)
    start("fini", FiniApp)


if __name__ == "__main__":
    main()
