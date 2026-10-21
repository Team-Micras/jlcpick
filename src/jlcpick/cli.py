"""Command-line entry point."""

import argparse

from jlcpick import __version__


def main(argv: list[str] | None = None) -> None:
    """Parse arguments and run the requested command."""
    parser = argparse.ArgumentParser(prog="jlcpick")
    parser.add_argument("--version", action="version", version=f"jlcpick {__version__}")
    parser.parse_args(argv)
    parser.print_help()
