"""Status helpers for rendering and polling behavior."""

from __future__ import annotations

from qiskit_serverless.core.job import STATUS_MAP

ANSI_RESET = "\033[0m"
ANSI_COLORS = {
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "gray": "\033[90m",
    "white_bright": "\033[97m",
}


def status_color(status: str) -> str:
    """Resolve status color by semantic group."""
    normalized = str(status or "").upper()
    if normalized.startswith("RUNNING"):
        return "yellow"
    if normalized in ("DONE", "SUCCEEDED"):
        return "green"
    if normalized in ("ERROR", "FAILED"):
        return "red"
    if normalized in ("CANCELED", "CANCELLED", "STOPPED"):
        return "magenta"
    if normalized == "QUEUED":
        return "cyan"
    if normalized in ("INITIALIZING", "PENDING"):
        return "blue"
    return "gray"


def colorize(text: str, color: str, enabled: bool) -> str:
    """Colorize text if ANSI output is enabled."""
    if not enabled:
        return text
    return f"{ANSI_COLORS[color]}{text}{ANSI_RESET}"


def runtime_is_terminal(status: str) -> bool:
    """Return whether a runtime status is terminal."""
    normalized = str(status or "").upper()
    return normalized in ("DONE", "ERROR", "CANCELED", "CANCELLED", "FAILED")


def map_serverless_status(status: str, sub_status: str | None) -> str:
    """Map serverless status to display status aligned with regular Job API."""
    display_status = sub_status if status == "RUNNING" and sub_status else status
    return STATUS_MAP.get(display_status, display_status)
