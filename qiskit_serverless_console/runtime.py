"""Runtime cache/index management with background polling."""

from __future__ import annotations

import time
from collections import deque
from threading import Event, Lock, Thread
from typing import Any

from qiskit_ibm_runtime import QiskitRuntimeService

from .status import runtime_is_terminal

DISCOVERY_BATCH_SIZE = 3
WORKER_TICK_SECONDS = 0.2
REDISCOVERY_INTERVAL_SECONDS = (
    5.0  # Re-discover runtime jobs for active serverless jobs
)


class RuntimeState:
    """Shared runtime job cache and updater worker."""

    def __init__(
        self,
        runtime_service: QiskitRuntimeService,
        serverless_client: Any,
        interval: int,
    ):
        self._runtime_service = runtime_service
        self._serverless_client = serverless_client
        self._interval = max(1, interval)
        self._lock = Lock()
        self._stop_event = Event()
        self._thread = Thread(target=self._refresh_worker, daemon=True)
        self.serverless_runtime_index: dict[str, list[str]] = {}
        self.runtime_cache: dict[str, dict[str, Any]] = {}
        self._discovery_queue: deque[str] = deque()
        self._discovery_pending: set[str] = set()
        self._discovery_done: set[str] = set()
        # Track which serverless jobs need continuous status refresh (non-terminal)
        self._active_serverless_jobs: set[str] = set()
        # Track terminal jobs that user expanded (on-demand status fetch trigger)
        self._expanded_terminal_jobs: set[str] = set()
        # Terminal jobs present on initial load: discover runtime IDs only, no status polling
        self._frozen_terminal_jobs: set[str] = set()
        # Track last rediscovery time for active jobs
        self._last_rediscovery_at: float = 0.0

    def start(self) -> None:
        """Start background runtime refresher."""
        self._thread.start()

    def stop(self) -> None:
        """Stop background runtime refresher."""
        self._stop_event.set()
        self._thread.join(timeout=2)

    def enqueue_runtime_discovery(
        self,
        serverless_job_ids: list[str],
        is_terminal: bool = False,
    ) -> None:
        """Queue runtime discovery for visible serverless jobs.

        Args:
            serverless_job_ids: List of serverless job IDs to discover runtime jobs for.
            is_terminal: If False, these jobs will have continuous status refresh.
                         If True, status refresh only happens when explicitly requested.
        """
        for job_id in serverless_job_ids:
            normalized_job_id = str(job_id)
            with self._lock:
                self.serverless_runtime_index.setdefault(normalized_job_id, [])
                if not is_terminal:
                    self._active_serverless_jobs.add(normalized_job_id)
                if (
                    normalized_job_id not in self._discovery_done
                    and normalized_job_id not in self._discovery_pending
                ):
                    self._discovery_queue.append(normalized_job_id)
                    self._discovery_pending.add(normalized_job_id)

    def mark_job_terminal(self, serverless_job_id: str) -> None:
        """Mark a serverless job as terminal (stop continuous refresh)."""
        with self._lock:
            self._active_serverless_jobs.discard(serverless_job_id)

    def request_status_refresh(self, serverless_job_id: str) -> None:
        """Request on-demand status refresh for a terminal job."""
        with self._lock:
            # If this was an initial frozen terminal job, unfreeze it on manual expand.
            if serverless_job_id in self._frozen_terminal_jobs:
                self._frozen_terminal_jobs.discard(serverless_job_id)
                for runtime_id in self.serverless_runtime_index.get(
                    serverless_job_id, []
                ):
                    if runtime_id in self.runtime_cache:
                        self.runtime_cache[runtime_id]["poll_enabled"] = True
            self._expanded_terminal_jobs.add(serverless_job_id)

    def freeze_terminal_jobs(self, serverless_job_ids: list[str]) -> None:
        """Freeze initial terminal jobs: keep discovery, skip runtime status refresh."""
        with self._lock:
            for job_id in serverless_job_ids:
                self._frozen_terminal_jobs.add(str(job_id))

    def is_discovery_done(self, serverless_job_id: str) -> bool:
        """Check if runtime discovery has completed for a serverless job."""
        with self._lock:
            return serverless_job_id in self._discovery_done

    def get_runtime_count(self, serverless_job_id: str) -> int | None:
        """Get runtime job count, or None if discovery not done yet."""
        with self._lock:
            if serverless_job_id not in self._discovery_done:
                return None
            return len(self.serverless_runtime_index.get(serverless_job_id, []))

    def attach_runtime_rows(self, rows: list[dict[str, Any]]) -> None:
        """Merge cached runtime status into output rows."""
        with self._lock:
            for row in rows:
                job_id = str(row.get("job_id"))
                runtime_ids = list(self.serverless_runtime_index.get(job_id, []))
                row["runtime_jobs"] = [
                    {
                        "runtime_job_id": runtime_id,
                        "backend": self.runtime_cache.get(runtime_id, {}).get(
                            "backend", "(unknown)"
                        ),
                        "status": self.runtime_cache.get(runtime_id, {}).get(
                            "status", ""
                        ),
                    }
                    for runtime_id in runtime_ids
                ]

    def _requeue_active_for_rediscovery(self) -> None:
        """Re-enqueue active serverless jobs for runtime rediscovery."""
        with self._lock:
            for job_id in self._active_serverless_jobs:
                if job_id in self._discovery_done:
                    self._discovery_done.discard(job_id)
                if job_id not in self._discovery_pending:
                    self._discovery_queue.append(job_id)
                    self._discovery_pending.add(job_id)

    def _discover_batch(self) -> None:
        batch: list[str] = []
        with self._lock:
            while self._discovery_queue and len(batch) < DISCOVERY_BATCH_SIZE:
                job_id = self._discovery_queue.popleft()
                self._discovery_pending.discard(job_id)
                batch.append(job_id)

        for job_id in batch:
            try:
                discovered_runtime_ids = self._serverless_client.runtime_jobs(job_id)
            except Exception:  # pylint: disable=broad-exception-caught
                discovered_runtime_ids = []

            with self._lock:
                runtime_ids_for_job = self.serverless_runtime_index.setdefault(
                    job_id, []
                )
                for runtime_id in discovered_runtime_ids or []:
                    normalized_runtime_id = str(runtime_id)
                    if normalized_runtime_id not in runtime_ids_for_job:
                        runtime_ids_for_job.append(normalized_runtime_id)
                    if normalized_runtime_id not in self.runtime_cache:
                        poll_enabled = job_id not in self._frozen_terminal_jobs
                        self.runtime_cache[normalized_runtime_id] = {
                            "status": "",
                            "backend": "(unknown)",
                            "terminal": False,
                            "poll_enabled": poll_enabled,
                        }
                    elif job_id in self._frozen_terminal_jobs:
                        self.runtime_cache[normalized_runtime_id][
                            "poll_enabled"
                        ] = False
                self._discovery_done.add(job_id)

    def _refresh_runtime_statuses(self) -> None:
        with self._lock:
            # Collect runtime IDs from active (non-terminal) serverless jobs
            active_runtime_ids: set[str] = set()
            for job_id in self._active_serverless_jobs:
                for runtime_id in self.serverless_runtime_index.get(job_id, []):
                    runtime_data = self.runtime_cache.get(runtime_id, {})
                    if not runtime_data.get("terminal", False) and runtime_data.get(
                        "poll_enabled", True
                    ):
                        active_runtime_ids.add(runtime_id)

            # Continue refreshing any non-terminal runtime even if its parent became terminal
            non_terminal_runtime_ids: set[str] = set()
            for runtime_id, runtime_data in self.runtime_cache.items():
                if not runtime_data.get("terminal", False) and runtime_data.get(
                    "poll_enabled", True
                ):
                    non_terminal_runtime_ids.add(runtime_id)

            # Collect runtime IDs from terminal jobs that user expanded
            expanded_runtime_ids: set[str] = set()
            expanded_jobs_to_process = set(self._expanded_terminal_jobs)
            for job_id in expanded_jobs_to_process:
                for runtime_id in self.serverless_runtime_index.get(job_id, []):
                    # Only fetch if we don't have status yet
                    runtime_data = self.runtime_cache.get(runtime_id, {})
                    if runtime_data.get("poll_enabled", True) and not runtime_data.get(
                        "status"
                    ):
                        expanded_runtime_ids.add(runtime_id)
            # Clear expanded jobs after collecting (one-time fetch)
            self._expanded_terminal_jobs.clear()

            runtime_ids = list(
                active_runtime_ids | non_terminal_runtime_ids | expanded_runtime_ids
            )

        for runtime_id in runtime_ids:
            try:
                runtime_job = self._runtime_service.job(runtime_id)
                status_value = runtime_job.status()
                status = (
                    str(status_value.value)
                    if hasattr(status_value, "value")
                    else str(status_value)
                )

                runtime_backend = getattr(runtime_job, "backend", None)
                if callable(runtime_backend):
                    runtime_backend = runtime_backend()
                backend_name = getattr(runtime_backend, "name", None)
                backend = (
                    str(backend_name)
                    if backend_name
                    else str(runtime_backend or "(unknown)")
                )

                with self._lock:
                    self.runtime_cache[runtime_id]["status"] = status
                    self.runtime_cache[runtime_id]["backend"] = backend
                    self.runtime_cache[runtime_id]["terminal"] = runtime_is_terminal(
                        status
                    )
            except Exception as error:  # pylint: disable=broad-exception-caught
                with self._lock:
                    self.runtime_cache[runtime_id]["status"] = f"UNAVAILABLE: {error}"
                    self.runtime_cache[runtime_id]["backend"] = self.runtime_cache[
                        runtime_id
                    ].get(
                        "backend",
                        "(unknown)",
                    )

    def _refresh_worker(self) -> None:
        next_status_refresh_at = 0.0
        next_rediscovery_at = 0.0
        while not self._stop_event.is_set():
            now = time.monotonic()

            # Periodically re-queue active jobs for runtime rediscovery
            if now >= next_rediscovery_at:
                self._requeue_active_for_rediscovery()
                next_rediscovery_at = now + REDISCOVERY_INTERVAL_SECONDS

            self._discover_batch()

            if now >= next_status_refresh_at:
                self._refresh_runtime_statuses()
                next_status_refresh_at = now + self._interval

            self._stop_event.wait(WORKER_TICK_SECONDS)
