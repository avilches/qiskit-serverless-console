"""CLI entrypoint for qiskit-serverless-jobs-watch."""

from __future__ import annotations

from .config import parse_options
from .watch import run_watch


def main() -> int:
    """CLI main entrypoint."""
    options = parse_options()
    return run_watch(options)


if __name__ == "__main__":
    raise SystemExit(main())
