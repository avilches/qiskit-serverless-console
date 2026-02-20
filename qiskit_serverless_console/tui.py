"""Interactive Textual UI for job watch mode."""

from __future__ import annotations

import threading
import time
from typing import Any

from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Static, Tree
from textual.containers import Horizontal, Vertical, VerticalScroll

from .config import WatchOptions, build_clients
from .fetch import fetch_serverless_rows
from .runtime import RuntimeState
from .status import status_color
from .timefmt import relative_created

# Unicode braille spinner frames for tree labels (Tree doesn't support Rich Spinner)
_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _field_or_blank(value: Any) -> str:
    return str(value or "").strip()


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


def _combined_status(status: Any, sub_status: Any) -> str:
    base = _field_or_blank(status) or "(unknown)"
    detail = _field_or_blank(sub_status)
    return f"{base} / {detail}" if detail else base


def _status_style(status_text: str, no_color: bool) -> str | None:
    if no_color:
        return None
    color = status_color(status_text)
    if color == "white_bright":
        return "bright_white"
    if color == "gray":
        return "bright_black"
    return color


class LogsScreen(ModalScreen[None]):
    """Modal screen to display job logs with scrollable content."""

    BINDINGS = [
        ("escape", "dismiss", "Esc Close"),
    ]

    CSS = """
    LogsScreen {
        align: center middle;
    }
    #logs-container {
        width: 90%;
        height: 90%;
        border: solid green;
        background: $surface;
        padding: 1 2;
    }
    #logs-content {
        width: 100%;
        height: 1fr;
    }
    """

    def __init__(self, job_id: str) -> None:
        super().__init__()
        self._job_id = job_id
        self._loading = True

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="logs-container"):
            yield Static(
                f"[bold]Logs for job: {self._job_id}[/bold]\n{'─' * 60}\n\n⠋ Loading logs...",
                id="logs-content",
                markup=True,
            )
        yield Footer()

    def on_mount(self) -> None:
        """Start spinner animation."""
        self._update_loading()
        self.set_interval(0.1, self._update_loading)

    def _update_loading(self) -> None:
        """Update the loading spinner."""
        if not self._loading:
            return
        content = self.query_one("#logs-content", Static)
        spinner_char = _SPINNER_FRAMES[int(time.monotonic() * 10) % len(_SPINNER_FRAMES)]
        content.update(
            f"[bold]Logs for job: {self._job_id}[/bold]\n{'─' * 60}\n\n{spinner_char} Loading logs..."
        )

    def set_logs(self, logs: str) -> None:
        """Update the screen with the fetched logs."""
        self._loading = False
        content = self.query_one("#logs-content", Static)
        header = f"[bold]Logs for job: {self._job_id}[/bold]\n{'─' * 60}\n\n"
        content.update(header + (logs or "(empty)"))

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Block dismiss action while loading."""
        if action == "dismiss" and self._loading:
            return False
        return True


class StopConfirmScreen(ModalScreen[None]):
    """Modal screen to confirm stopping a job (serverless or runtime)."""

    BINDINGS = [
        ("escape", "dismiss", "Esc Cancel"),
    ]

    CSS = """
    StopConfirmScreen {
        align: center middle;
    }
    #stop-container {
        width: 60;
        height: auto;
        border: solid yellow;
        background: $surface;
        padding: 1 2;
    }
    #stop-message {
        width: 100%;
        text-align: center;
        margin-bottom: 1;
    }
    #stop-buttons {
        width: 100%;
        height: 3;
        align: center middle;
    }
    #stop-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(
        self,
        job_id: str,
        job_type: str,
        serverless_client: Any | None = None,
        runtime_service: Any | None = None,
    ) -> None:
        super().__init__()
        self._job_id = job_id
        self._job_type = job_type  # "serverless" or "runtime"
        self._serverless_client = serverless_client
        self._runtime_service = runtime_service
        self._confirming = True
        self._stopping = False

    def compose(self) -> ComposeResult:
        job_type_label = "runtime job" if self._job_type == "runtime" else "job"
        with Vertical(id="stop-container"):
            yield Static(
                f"[bold]Stop {job_type_label}?[/bold]\n\n"
                f"[bright_white]{self._job_id}[/bright_white]",
                id="stop-message",
                markup=True,
            )
            with Horizontal(id="stop-buttons"):
                yield Button("Ok", variant="primary", id="ok-btn")
                yield Button("Esc=Cancel", variant="default", id="cancel-btn")

    def on_mount(self) -> None:
        """Focus the Ok button by default."""
        self.query_one("#ok-btn", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "ok-btn" and self._confirming:
            self._start_stop()
        elif event.button.id in ("cancel-btn", "close-btn"):
            self.dismiss()

    def _start_stop(self) -> None:
        """Start the stop operation."""
        self._confirming = False
        self._stopping = True
        message = self.query_one("#stop-message", Static)
        spinner_char = _SPINNER_FRAMES[0]
        job_type_label = "runtime job" if self._job_type == "runtime" else "job"
        message.update(
            f"[bold]{spinner_char} Stopping {job_type_label}...[/bold]\n\n"
            f"[bright_white]{self._job_id}[/bright_white]"
        )
        self.query_one("#ok-btn", Button).disabled = True
        self.query_one("#cancel-btn", Button).disabled = True
        self.set_interval(0.1, self._update_stopping)
        thread = threading.Thread(target=self._perform_stop, daemon=True)
        thread.start()

    def _update_stopping(self) -> None:
        """Update spinner during stop operation."""
        if not self._stopping:
            return
        message = self.query_one("#stop-message", Static)
        spinner_char = _SPINNER_FRAMES[int(time.monotonic() * 10) % len(_SPINNER_FRAMES)]
        job_type_label = "runtime job" if self._job_type == "runtime" else "job"
        message.update(
            f"[bold]{spinner_char} Stopping {job_type_label}...[/bold]\n\n"
            f"[bright_white]{self._job_id}[/bright_white]"
        )

    def _perform_stop(self) -> None:
        """Perform the stop operation in background thread."""
        try:
            if self._job_type == "runtime" and self._runtime_service is not None:
                job = self._runtime_service.job(self._job_id)
                job.cancel()
            elif self._serverless_client is not None:
                job = self._serverless_client.job(self._job_id)
                job.stop()
            else:
                raise ValueError("No client available")
            self.app.call_from_thread(self._set_result, True, None)
        except Exception as error:  # pylint: disable=broad-exception-caught
            self.app.call_from_thread(self._set_result, False, str(error))

    def _set_result(self, success: bool, error: str | None) -> None:
        """Update screen with stop result."""
        self._stopping = False
        message = self.query_one("#stop-message", Static)
        job_type_label = "Runtime job" if self._job_type == "runtime" else "Job"
        if success:
            message.update(
                f"[bold green]{job_type_label} stopped[/bold green]\n\n"
                f"[bright_white]{self._job_id}[/bright_white]"
            )
        else:
            message.update(
                f"[bold red]Failed to stop {job_type_label.lower()}[/bold red]\n\n"
                f"[bright_white]{self._job_id}[/bright_white]\n\n"
                f"{error or 'Unknown error'}"
            )
        buttons = self.query_one("#stop-buttons", Horizontal)
        for child in list(buttons.children):
            child.remove()
        close_btn = Button("Close", variant="primary", id="close-btn")
        buttons.mount(close_btn)
        close_btn.focus()


class JobsTreeApp(App[int]):
    """Keyboard-driven tree UI for serverless/runtime jobs."""

    TITLE = "Qiskit Serverless Console"

    CSS = """
    Screen {
        layout: vertical;
    }
    #status {
        height: 1;
        padding: 0 1;
    }
    #jobs {
        height: 1fr;
    }
    """

    BINDINGS = [
        ("up", "tree_cursor_up", "↑ Move up"),
        ("down", "tree_cursor_down", "↓ Move down"),
        ("enter", "toggle_selected", "Enter Expand/Collapse"),
        ("l", "show_logs", "L Logs"),
        ("s", "stop_job", "S Stop"),
        ("q", "quit", "Q Quit"),
    ]

    def action_tree_cursor_up(self) -> None:
        tree = self.query_one("#jobs", Tree)
        tree.action_cursor_up()

    def action_tree_cursor_down(self) -> None:
        tree = self.query_one("#jobs", Tree)
        tree.action_cursor_down()

    def __init__(self, options: WatchOptions) -> None:
        super().__init__()
        self.options = options
        self._rows: list[dict[str, Any]] = []
        self._job_nodes: dict[str, Any] = {}  # job_id -> TreeNode
        self._job_terminal_status: dict[str, bool] = {}  # job_id -> is_terminal
        self._job_runtime_count: dict[str, int] = {}  # job_id -> runtime count (for auto-expand)
        self._runtime_status: dict[str, str] = {}  # runtime_job_id -> latest status
        self._initial_terminal_jobs: set[str] = set()
        self._fetch_inflight = False
        self._next_fetch_at = 0.0
        self._first_fetch = True
        self._last_error: str | None = None
        self._status_text = "Connecting to Qiskit services..."
        self._serverless_client: Any | None = None
        self._runtime_state: RuntimeState | None = None
        self._spinner_frame = 0  # For animating tree label spinners

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static("", id="status")
        yield Tree("Serverless jobs", id="jobs")
        yield Footer()

    def on_mount(self) -> None:
        tree = self.query_one("#jobs", Tree)
        tree.show_root = True
        tree.root.expand()
        self.set_interval(0.2, self._tick)
        self._render_status()
        self._render_tree()

    def on_tree_node_expanded(self, event: Tree.NodeExpanded[dict[str, str]]) -> None:
        """Request status refresh when user expands a terminal job."""
        data = event.node.data or {}
        if data.get("type") == "job" and data.get("job_id"):
            job_id = data["job_id"]
            if self._runtime_state is not None:
                self._runtime_state.request_status_refresh(job_id)

    def on_unmount(self) -> None:
        if self._runtime_state is not None:
            self._runtime_state.stop()

    def action_toggle_selected(self) -> None:
        tree = self.query_one("#jobs", Tree)
        node = tree.cursor_node
        if node is not None and node.allow_expand:
            tree.action_toggle_node()

    def action_show_logs(self) -> None:
        """Show logs for the selected serverless job."""
        tree = self.query_one("#jobs", Tree)
        node = tree.cursor_node
        if node is None:
            return
        data = node.data or {}
        # Get job_id from either a job node or a runtime node (which also has job_id)
        job_id = data.get("job_id")
        if not job_id:
            return
        if self._serverless_client is None:
            return
        # Show modal immediately with loading spinner
        logs_screen = LogsScreen(job_id)
        self.push_screen(logs_screen)
        # Fetch logs in background thread
        thread = threading.Thread(
            target=self._fetch_logs, args=(job_id, logs_screen), daemon=True
        )
        thread.start()

    def _fetch_logs(self, job_id: str, logs_screen: LogsScreen) -> None:
        """Fetch logs from the API and update the modal."""
        try:
            job = self._serverless_client.job(job_id)
            logs = job.logs()
        except Exception as error:  # pylint: disable=broad-exception-caught
            logs = f"Error fetching logs: {error}"
        self.call_from_thread(logs_screen.set_logs, logs)

    def action_stop_job(self) -> None:
        """Show confirmation to stop the selected job (serverless or runtime)."""
        tree = self.query_one("#jobs", Tree)
        node = tree.cursor_node
        if node is None:
            return
        data = node.data or {}
        node_type = data.get("type")

        if node_type == "job":
            # Serverless job
            job_id = data.get("job_id")
            if not job_id or self._serverless_client is None:
                return
            # Don't allow stopping terminal serverless jobs
            if self._job_terminal_status.get(job_id, False):
                return
            stop_screen = StopConfirmScreen(
                job_id=job_id,
                job_type="serverless",
                serverless_client=self._serverless_client,
            )
            self.push_screen(stop_screen)

        elif node_type == "runtime":
            # Runtime job
            runtime_job_id = data.get("runtime_job_id")
            if not runtime_job_id or self._runtime_state is None:
                return
            # Don't allow stopping terminal runtime jobs
            runtime_status = self._runtime_status.get(runtime_job_id, "")
            if _is_terminal_status(runtime_status):
                return
            stop_screen = StopConfirmScreen(
                job_id=runtime_job_id,
                job_type="runtime",
                runtime_service=self._runtime_state.runtime_service,
            )
            self.push_screen(stop_screen)

    def _tick(self) -> None:
        self._spinner_frame = (self._spinner_frame + 1) % len(_SPINNER_FRAMES)
        if self._runtime_state is not None:
            self._runtime_state.attach_runtime_rows(self._rows)
        self._kick_fetch_if_due()
        self._render_status()
        self._render_tree()
        # Force tree refresh to ensure new nodes are visible
        tree_query = self.query("#jobs")
        if tree_query:
            tree_query.first(Tree).refresh()

    def _kick_fetch_if_due(self) -> None:
        if self._fetch_inflight:
            return
        if time.monotonic() < self._next_fetch_at:
            return
        self._fetch_inflight = True
        if self._first_fetch:
            self._status_text = "Loading serverless jobs..."
        thread = threading.Thread(target=self._fetch_once, daemon=True)
        thread.start()

    def _fetch_once(self) -> None:
        try:
            if self._serverless_client is None or self._runtime_state is None:
                serverless_client, runtime_service = build_clients()
                self._serverless_client = serverless_client
                self._runtime_state = RuntimeState(
                    runtime_service=runtime_service,
                    serverless_client=serverless_client,
                    interval=self.options.interval,
                )
                self._runtime_state.start()

            assert self._serverless_client is not None
            rows = fetch_serverless_rows(
                client=self._serverless_client,
                statuses=self.options.status,
                created_after_iso=None,
                limit=self.options.limit,
                offset=self.options.offset,
            )

            if self.options.job_id:
                rows = [row for row in rows if row.get("job_id") == self.options.job_id]
            if self.options.function:
                rows = [row for row in rows if row.get("function") == self.options.function]

            assert self._runtime_state is not None
            # Separate terminal and non-terminal jobs for different refresh strategies
            terminal_job_ids = [
                str(row.get("job_id"))
                for row in rows
                if _is_terminal_status(row.get("status"))
            ]
            if self._first_fetch:
                self._runtime_state.freeze_terminal_jobs(terminal_job_ids)
                self._initial_terminal_jobs = set(terminal_job_ids)
            active_job_ids = [
                str(row.get("job_id"))
                for row in rows
                if not _is_terminal_status(row.get("status"))
            ]
            # Non-terminal jobs get continuous status refresh
            self._runtime_state.enqueue_runtime_discovery(
                serverless_job_ids=active_job_ids,
                is_terminal=False,
            )
            # Terminal jobs only get discovery, status refresh on expand
            self._runtime_state.enqueue_runtime_discovery(
                serverless_job_ids=terminal_job_ids,
                is_terminal=True,
            )
            self.call_from_thread(self._apply_fetch_result, rows, None)
        except Exception as error:  # pylint: disable=broad-exception-caught
            self.call_from_thread(self._apply_fetch_result, None, str(error))

    def _apply_fetch_result(
        self, rows: list[dict[str, Any]] | None, error: str | None
    ) -> None:
        self._fetch_inflight = False
        if error:
            self._last_error = error
            self._status_text = f"Error: {error}"
            self._next_fetch_at = time.monotonic() + max(1, self.options.interval)
            return

        self._last_error = None
        self._rows = rows or []
        self._first_fetch = False
        self._next_fetch_at = time.monotonic() + self.options.interval
        self._status_text = ""

    def _render_status(self) -> None:
        status_query = self.query("#status")
        if not status_query:
            return  # Modal is active, skip rendering
        status = status_query.first(Static)
        if self._fetch_inflight:
            row = Table.grid(padding=(0, 1))
            row.add_row(Spinner("dots", style="bright_black"), Text(self._status_text))
            status.update(row)
            return
        if self._last_error:
            status.update(Text(self._status_text, style="red"))
            return
        status.update("")

    def _make_job_label(
        self, row: dict[str, Any], loading_runtimes: bool = False
    ) -> Text:
        job_id = _field_or_blank(row.get("job_id")) or "(unknown)"
        combined_status = _combined_status(row.get("status"), row.get("sub_status"))
        created = (
            relative_created(row.get("created"))
            if row.get("created")
            else "(unknown)"
        )
        parts: list[Text | str] = [
            Text(_field_or_blank(row.get("function")) or "(unknown)"),
            " ",
            Text(job_id, style=None if self.options.no_color else "bright_white"),
            " ",
            Text(
                combined_status or "(unknown)",
                style=_status_style(combined_status, self.options.no_color),
            ),
            " ",
            Text(created, style=None if self.options.no_color else "bright_black"),
        ]
        if loading_runtimes:
            spinner_char = _SPINNER_FRAMES[self._spinner_frame]
            parts.append(" ")
            parts.append(
                Text(spinner_char, style=None if self.options.no_color else "bright_black")
            )
        return Text.assemble(*parts)

    def _make_runtime_label(self, runtime: dict[str, Any]) -> Text:
        runtime_status = _field_or_blank(runtime.get("status"))
        backend = _field_or_blank(runtime.get("backend"))
        runtime_id = _field_or_blank(runtime.get("runtime_job_id")) or "(unknown)"

        # Show spinner when status is unknown (still loading)
        if not runtime_status:
            spinner_char = _SPINNER_FRAMES[self._spinner_frame]
            return Text.assemble(
                Text(
                    runtime_id,
                    style=None if self.options.no_color else "bright_white",
                ),
                " ",
                Text(spinner_char, style=None if self.options.no_color else "bright_black"),
            )

        runtime_spinning = not _is_terminal_status(runtime_status)
        backend_display = (
            "(unknown)"
            if runtime_spinning and (not backend or backend == "(unknown)")
            else (backend or "(unknown)")
        )
        return Text.assemble(
            Text(
                runtime_id,
                style=None if self.options.no_color else "bright_white",
            ),
            " ",
            Text(
                runtime_status,
                style=_status_style(runtime_status, self.options.no_color),
            ),
            " ",
            Text(
                backend_display,
                style=None if self.options.no_color else "bright_black",
            ),
        )

    def _render_tree(self) -> None:
        tree_query = self.query("#jobs")
        if not tree_query:
            return  # Modal is active, skip rendering
        tree = tree_query.first(Tree)
        root = tree.root

        # Ensure root is always expanded
        if not root.is_expanded:
            root.expand()

        rows_sorted = sorted(
            self._rows, key=lambda row: str(row.get("created") or ""), reverse=True
        )[: max(1, self.options.limit)]

        current_job_ids = {
            _field_or_blank(row.get("job_id")) or "(unknown)" for row in rows_sorted
        }

        # Remove jobs that no longer exist
        stale_job_ids = set(self._job_nodes.keys()) - current_job_ids
        for job_id in stale_job_ids:
            node = self._job_nodes.pop(job_id, None)
            self._job_terminal_status.pop(job_id, None)
            self._job_runtime_count.pop(job_id, None)
            if node is not None:
                node.remove()

        visible_runtime_ids: set[str] = set()

        # Process in reverse order so that when using before=0,
        # newer jobs end up at the top
        for row in reversed(rows_sorted):
            job_id = _field_or_blank(row.get("job_id")) or "(unknown)"
            base_status = _field_or_blank(row.get("status"))
            is_terminal = _is_terminal_status(base_status)

            # Check runtime discovery status for terminal jobs
            runtime_count: int | None = None
            if self._runtime_state is not None and is_terminal:
                runtime_count = self._runtime_state.get_runtime_count(job_id)

            # Show spinner for non-terminal jobs (can receive new runtime jobs anytime)
            loading_runtimes = not is_terminal
            job_label = self._make_job_label(row, loading_runtimes=loading_runtimes)

            if job_id in self._job_nodes:
                # Update existing node
                job_node = self._job_nodes[job_id]
                job_node.set_label(job_label)

                # Detect transition from non-terminal to terminal
                was_terminal = self._job_terminal_status.get(job_id, False)
                if is_terminal and not was_terminal:
                    if self._runtime_state is not None:
                        self._runtime_state.mark_job_terminal(job_id)
                self._job_terminal_status[job_id] = is_terminal

                # Update allow_expand for terminal jobs based on discovery
                if is_terminal and runtime_count is not None:
                    job_node.allow_expand = runtime_count > 0
            else:
                # Create new node
                if is_terminal:
                    # Terminal: closed, expandable only if has runtime jobs
                    can_expand = runtime_count is not None and runtime_count > 0
                    job_node = root.add(
                        job_label,
                        data={"type": "job", "job_id": job_id},
                        expand=False,
                        allow_expand=can_expand,
                        before=0,
                    )
                else:
                    # Non-terminal: open, always expandable
                    job_node = root.add(
                        job_label,
                        data={"type": "job", "job_id": job_id},
                        expand=True,
                        before=0,
                    )
                self._job_nodes[job_id] = job_node
                self._job_terminal_status[job_id] = is_terminal

            # Update runtime children
            runtimes = row.get("runtime_jobs", []) or []
            current_runtime_count = len(runtimes)
            previous_runtime_count = self._job_runtime_count.get(job_id, 0)
            # Avoid dropping already discovered runtime children when a transient
            # lazy refresh returns an empty runtime list.
            preserve_existing_runtime_children = (
                is_terminal and previous_runtime_count > 0
            ) or (current_runtime_count == 0 and previous_runtime_count > 0)

            # Update allow_expand for all jobs based on runtime count
            if current_runtime_count > 0:
                job_node.allow_expand = True

            # Auto-expand when new runtime jobs appear for non-terminal jobs.
            # For terminal jobs, expansion is still driven by runtime status updates below.
            if (
                not is_terminal
                and current_runtime_count > previous_runtime_count
                and current_runtime_count > 0
            ):
                job_node.expand()

            self._job_runtime_count[job_id] = (
                max(previous_runtime_count, current_runtime_count)
                if preserve_existing_runtime_children
                else current_runtime_count
            )

            current_runtime_ids = {
                _field_or_blank(rt.get("runtime_job_id")) or "(unknown)"
                for rt in runtimes
            }

            # Build index of existing runtime nodes
            existing_runtime_nodes: dict[str, Any] = {}
            for child in list(job_node.children):
                data = child.data or {}
                if data.get("type") == "runtime":
                    rt_id = data.get("runtime_job_id", "")
                    if preserve_existing_runtime_children or rt_id in current_runtime_ids:
                        existing_runtime_nodes[rt_id] = child
                    else:
                        child.remove()

            if preserve_existing_runtime_children:
                visible_runtime_ids.update(existing_runtime_nodes.keys())

            for runtime in runtimes:
                runtime_id = _field_or_blank(runtime.get("runtime_job_id")) or "(unknown)"
                visible_runtime_ids.add(runtime_id)
                runtime_label = self._make_runtime_label(runtime)
                runtime_status = _field_or_blank(runtime.get("status"))
                previous_runtime_status = self._runtime_status.get(runtime_id, "")
                status_changed = (
                    runtime_id in self._runtime_status
                    and runtime_status != previous_runtime_status
                )
                self._runtime_status[runtime_id] = runtime_status

                if runtime_id in existing_runtime_nodes:
                    existing_runtime_nodes[runtime_id].set_label(runtime_label)
                else:
                    job_node.add_leaf(
                        runtime_label,
                        data={
                            "type": "runtime",
                            "job_id": job_id,
                            "runtime_job_id": runtime_id,
                        },
                    )

                if status_changed and job_id not in self._initial_terminal_jobs:
                    job_node.expand()

        stale_runtime_ids = set(self._runtime_status.keys()) - visible_runtime_ids
        for runtime_id in stale_runtime_ids:
            self._runtime_status.pop(runtime_id, None)
