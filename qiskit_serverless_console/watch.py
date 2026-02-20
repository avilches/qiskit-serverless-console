"""Foreground watch loop orchestration."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

from .config import (
    DEFAULT_CHANNEL,
    DEFAULT_GATEWAY_HOST,
    DEFAULT_RUNTIME_URL,
    ENV_GATEWAY_PROVIDER_HOST,
    ENV_QISKIT_IBM_CHANNEL,
    ENV_QISKIT_IBM_INSTANCE,
    ENV_QISKIT_IBM_TOKEN,
    ENV_QISKIT_IBM_URL,
    WatchOptions,
    build_clients,
)
from .fetch import fetch_serverless_rows
from .runtime import RuntimeState
from .tui import JobsTreeApp


def _mask_secret(value: str | None) -> str:
    if not value:
        return "(missing)"
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}...{value[-3:]}"


def _print_startup_env() -> None:
    gateway_host = os.getenv(ENV_GATEWAY_PROVIDER_HOST, DEFAULT_GATEWAY_HOST)
    runtime_url = os.getenv(ENV_QISKIT_IBM_URL, DEFAULT_RUNTIME_URL)
    runtime_channel = os.getenv(ENV_QISKIT_IBM_CHANNEL, DEFAULT_CHANNEL)
    instance = os.getenv(ENV_QISKIT_IBM_INSTANCE)
    token = os.getenv(ENV_QISKIT_IBM_TOKEN)

    print("Environment in use:")
    print(f"  {ENV_GATEWAY_PROVIDER_HOST}={gateway_host}")
    print(f"  {ENV_QISKIT_IBM_INSTANCE}={instance or '(missing)'}")
    print(f"  {ENV_QISKIT_IBM_TOKEN}={_mask_secret(token)}")
    print(f"  {ENV_QISKIT_IBM_URL}={runtime_url}")
    print(f"  {ENV_QISKIT_IBM_CHANNEL}={runtime_channel}")
    print("")


def _suppress_noisy_qiskit_logs() -> None:
    noisy_loggers = (
        "qiskit_runtime_service",
        "qiskit_runtime_service._discover_account",
        "qiskit_ibm_runtime",
    )
    for logger_name in noisy_loggers:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.ERROR)
        logger.propagate = False


def _run_json_watch(options: WatchOptions) -> int:
    serverless_client, runtime_service = build_clients()
    runtime_state = RuntimeState(
        runtime_service=runtime_service,
        serverless_client=serverless_client,
        interval=options.interval,
    )
    runtime_state.start()
    rows: list[dict[str, object]] = []
    next_fetch_at = 0.0
    first_fetch = True

    try:
        while True:
            now = time.monotonic()
            if now >= next_fetch_at:
                rows = fetch_serverless_rows(
                    client=serverless_client,
                    statuses=options.status,
                    created_after_iso=None,
                    limit=options.limit,
                    offset=options.offset,
                )

                if options.job_id:
                    rows = [row for row in rows if row.get("job_id") == options.job_id]
                if options.function:
                    rows = [
                        row for row in rows if row.get("function") == options.function
                    ]

                terminal_job_ids = [
                    str(row.get("job_id"))
                    for row in rows
                    if str(row.get("status") or "").strip().upper()
                    in (
                        "DONE",
                        "SUCCEEDED",
                        "ERROR",
                        "FAILED",
                        "CANCELED",
                        "CANCELLED",
                        "STOPPED",
                    )
                ]
                if first_fetch:
                    runtime_state.freeze_terminal_jobs(terminal_job_ids)
                    first_fetch = False

                runtime_state.enqueue_runtime_discovery(
                    serverless_job_ids=[str(row.get("job_id")) for row in rows],
                )
                next_fetch_at = now + options.interval

            runtime_state.attach_runtime_rows(rows)
            payload = {
                "refreshed_at": datetime.now(timezone.utc).isoformat(),
                "rows": rows,
            }
            print(json.dumps(payload, default=str))
            time.sleep(float(options.interval))
    except KeyboardInterrupt:
        runtime_state.stop()
        print("\nExiting.")
        return 0
    except Exception as error:  # pylint: disable=broad-exception-caught
        runtime_state.stop()
        print(f"Error: {error}", file=sys.stderr)
        return 1


def run_watch(options: WatchOptions) -> int:
    """Run watch loop until interrupted."""
    # _print_startup_env()
    _suppress_noisy_qiskit_logs()
    if options.json_mode:
        return _run_json_watch(options)
    app = JobsTreeApp(options)
    app.run()
    return 0
