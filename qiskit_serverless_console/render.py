"""Terminal and JSON rendering for watch output."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from rich.console import Console, RenderableType
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from .config import WatchOptions
from .status import status_color
from .timefmt import relative_created

_CONSOLES: dict[bool, Console] = {}
_LIVES: dict[bool, Live] = {}


def truncate(value: str, width: int) -> str:
    """Clamp text to a fixed cell width."""
    if len(value) <= width:
        return value
    if width <= 3:
        return value[:width]
    return f"{value[: max(1, width - 3)]}..."


def _get_console(no_color: bool) -> Console:
    console = _CONSOLES.get(no_color)
    if console is None:
        console = Console(no_color=no_color, soft_wrap=True)
        _CONSOLES[no_color] = console
    return console


def _get_live(no_color: bool) -> Live:
    live = _LIVES.get(no_color)
    if live is None:
        live = Live(
            console=_get_console(no_color),
            auto_refresh=True,
            screen=False,
            transient=False,
        )
        live.start()
        _LIVES[no_color] = live
    return live


def shutdown_render() -> None:
    """Stop active rich Live contexts."""
    for live in list(_LIVES.values()):
        live.stop()
    _LIVES.clear()


def _rich_style(color_name: str) -> str:
    mapping = {
        "white_bright": "bright_white",
        "gray": "bright_black",
    }
    return mapping.get(color_name, color_name)


def _field_or_blank(value: Any) -> str:
    return str(value or "").strip()


def _text_or_spinner(
    value: Any, style: str | None = None, width: int | None = None
) -> RenderableType:
    text = _field_or_blank(value)
    if width is not None and text:
        text = truncate(text, width)
    if not text or text == "(unknown)":
        return Spinner("dots", style="bright_black")
    return Text(text, style=style)


def _is_terminal_status(value: Any) -> bool:
    normalized = _field_or_blank(value).upper()
    return normalized in (
        "DONE",
        "SUCCEEDED",
        "ERROR",
        "FAILED",
        "CANCELED",
        "CANCELLED",
        "STOPPED",
    )


def _status_cell(text: str, style: str, spinning: bool) -> RenderableType:
    if not spinning:
        return Text(text, style=style)
    if not text:
        return Spinner("dots", style="bright_black")
    cell = Table.grid(padding=(0, 1))
    cell.add_row(Text(text, style=style), Spinner("dots", style="bright_black"))
    return cell


def _combined_status(status: Any, sub_status: Any) -> str:
    base = _field_or_blank(status) or "(unknown)"
    detail = _field_or_blank(sub_status)
    if detail:
        return f"{base} / {detail}"
    return base


def render_rows(rows: list[dict[str, Any]], options: WatchOptions) -> None:
    """Render either table output or NDJSON payload."""
    if options.json_mode:
        payload = {"refreshed_at": datetime.now(timezone.utc).isoformat(), "rows": rows}
        print(json.dumps(payload, default=str))
        return
    _print_tree(rows, options)


def render_loading(options: WatchOptions, message: str) -> None:
    """Render a lightweight loading screen while blocking setup/fetch runs."""
    if options.json_mode:
        return
    live = _get_live(options.no_color)
    loading = Table.grid(padding=(0, 1))
    loading.add_row(Spinner("dots", style="bright_black"), Text(message, style="bold"))
    live.update(loading, refresh=True)


def _print_tree(rows: list[dict[str, Any]], options: WatchOptions) -> None:
    console = _get_console(options.no_color)
    live = _get_live(options.no_color)
    if not rows:
        live.update(Text("(no jobs)", style="bright_black"), refresh=True)
        return

    rows_sorted = sorted(
        rows, key=lambda row: str(row.get("created") or ""), reverse=True
    )
    candidate_rows = rows_sorted[: max(1, options.limit)]
    root = Tree(Text("Serverless jobs", style="bold"))
    line_budget = max(3, console.size.height - 2)
    used_lines = 1  # Root tree line.

    for row in candidate_rows:
        if used_lines + 1 > line_budget:
            break

        base_job_status_text = _field_or_blank(row.get("status"))
        merged_job_status = _combined_status(row.get("status"), row.get("sub_status"))
        job_status_text = truncate(merged_job_status, 32) if merged_job_status else ""
        job_status_spinning = not _is_terminal_status(base_job_status_text)
        created_raw = row.get("created")
        created_text = relative_created(created_raw) if created_raw else None
        job_table = Table.grid(padding=(0, 1))
        job_table.add_row(
            _text_or_spinner(row.get("function"), width=24),
            _text_or_spinner(row.get("job_id"), style="bright_white", width=38),
            _status_cell(
                job_status_text,
                style=_rich_style(status_color(base_job_status_text)),
                spinning=job_status_spinning,
            ),
            _text_or_spinner(created_text, style="bright_black"),
        )
        job_node = root.add(job_table)

        used_lines += 1
        runtime_jobs = row.get("runtime_jobs", []) or []
        max_runtime_lines = max(0, line_budget - used_lines)
        shown_runtime = runtime_jobs[:max_runtime_lines]
        for runtime in shown_runtime:
            runtime_status_text = _field_or_blank(runtime.get("status"))
            runtime_status_spinning = not _is_terminal_status(runtime_status_text)
            backend_text = _field_or_blank(runtime.get("backend"))
            runtime_table = Table.grid(padding=(0, 1))
            runtime_table.add_row(
                _text_or_spinner(runtime.get("runtime_job_id"), style="bright_white"),
                _status_cell(
                    runtime_status_text,
                    style=_rich_style(status_color(runtime_status_text)),
                    spinning=runtime_status_spinning,
                ),
                (
                    Text("(unknown)", style="bright_black")
                    if runtime_status_spinning
                    and (not backend_text or backend_text == "(unknown)")
                    else _text_or_spinner(backend_text, style="bright_black")
                ),
            )
            job_node.add(runtime_table)
        used_lines += len(shown_runtime)

        hidden_runtime = len(runtime_jobs) - len(shown_runtime)
        if hidden_runtime > 0 and used_lines < line_budget:
            job_node.add(
                Text(
                    f"... {hidden_runtime} more runtime jobs",
                    style="bright_black",
                )
            )
            used_lines += 1
            break

    live.update(root, refresh=True)
