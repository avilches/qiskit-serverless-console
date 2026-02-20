"""CLI and environment configuration helpers."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass

from qiskit_ibm_runtime import QiskitRuntimeService
from qiskit_serverless import ServerlessClient

ENV_GATEWAY_PROVIDER_HOST = "ENV_GATEWAY_PROVIDER_HOST"
ENV_GATEWAY_PROVIDER_TOKEN = "ENV_GATEWAY_PROVIDER_TOKEN"
ENV_QISKIT_IBM_INSTANCE = "QISKIT_IBM_INSTANCE"
ENV_QISKIT_IBM_TOKEN = "QISKIT_IBM_TOKEN"
ENV_QISKIT_IBM_URL = "QISKIT_IBM_URL"
ENV_QISKIT_IBM_CHANNEL = "QISKIT_IBM_CHANNEL"

DEFAULT_GATEWAY_HOST = "https://qiskit-serverless.quantum.ibm.com"
DEFAULT_RUNTIME_URL = "https://cloud.ibm.com"
DEFAULT_CHANNEL = "ibm_quantum_platform"


@dataclass(frozen=True)
class WatchOptions:
    """Parsed watch options from CLI arguments."""

    job_id: str | None
    function: str | None
    status: list[str] | None
    last_hours: float
    limit: int
    offset: int
    interval: int
    json_mode: bool
    no_color: bool


def build_parser() -> argparse.ArgumentParser:
    """Build argument parser with only non-env options."""
    parser = argparse.ArgumentParser(
        prog="qiskit-serverless-jobs-watch",
        description="Watch Serverless and Runtime job statuses in a refreshing terminal view.",
    )
    parser.add_argument(
        "--job-id", default=None, help="Filter output to a single serverless job id."
    )
    parser.add_argument("--function", default=None, help="Function title filter.")
    parser.add_argument(
        "--status",
        action="append",
        default=None,
        help="Repeatable status filter (e.g. --status RUNNING --status QUEUED).",
    )
    parser.add_argument(
        "--last-hours",
        type=float,
        default=2.0,
        help="Show jobs created in the last N hours.",
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--interval", type=int, default=1)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print newline-delimited JSON instead of table.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colors in terminal output.",
    )
    return parser


def parse_options() -> WatchOptions:
    """Parse CLI options and validate required environment variables."""
    parser = build_parser()
    args = parser.parse_args()

    if not os.getenv(ENV_QISKIT_IBM_INSTANCE):
        parser.error(f"Missing env var `{ENV_QISKIT_IBM_INSTANCE}`.")
    if not os.getenv(ENV_QISKIT_IBM_TOKEN):
        parser.error(f"Missing env var `{ENV_QISKIT_IBM_TOKEN}`.")

    return WatchOptions(
        job_id=args.job_id,
        function=args.function,
        status=args.status,
        last_hours=args.last_hours,
        limit=args.limit,
        offset=args.offset,
        interval=max(1, args.interval),
        json_mode=bool(args.json),
        no_color=bool(args.no_color),
    )


def build_clients() -> tuple[ServerlessClient, QiskitRuntimeService]:
    """Construct API clients from environment variables."""
    instance = os.getenv(ENV_QISKIT_IBM_INSTANCE)
    ibm_token = os.getenv(ENV_QISKIT_IBM_TOKEN)
    gateway_host = os.getenv(ENV_GATEWAY_PROVIDER_HOST, DEFAULT_GATEWAY_HOST)
    gateway_token = os.getenv(ENV_GATEWAY_PROVIDER_TOKEN, ibm_token)

    serverless_client = ServerlessClient(
        host=gateway_host,
        token=gateway_token,
        instance=instance,
        channel=DEFAULT_CHANNEL,
    )

    runtime_service = QiskitRuntimeService(
        channel=os.getenv(ENV_QISKIT_IBM_CHANNEL, DEFAULT_CHANNEL),
        token=ibm_token,
        instance=instance,
        url=os.getenv(ENV_QISKIT_IBM_URL, DEFAULT_RUNTIME_URL),
    )
    return serverless_client, runtime_service
