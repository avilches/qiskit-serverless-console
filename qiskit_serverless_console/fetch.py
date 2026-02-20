"""API fetching and row normalization."""

from __future__ import annotations

from typing import Any

from qiskit_serverless import ServerlessClient

from .status import map_serverless_status


def _provider_name_from(
    data: dict[str, Any], program_data: dict[str, Any]
) -> str | None:
    provider_data = program_data.get("provider")
    if isinstance(provider_data, dict):
        name = provider_data.get("name")
        if name:
            return str(name)
    elif provider_data:
        return str(provider_data)

    top_level_provider = data.get("provider")
    if isinstance(top_level_provider, dict):
        name = top_level_provider.get("name")
        if name:
            return str(name)
    elif top_level_provider:
        return str(top_level_provider)
    return None


def _display_function_name(data: dict[str, Any]) -> str | None:
    program_data = data.get("program") or {}
    function_name = program_data.get("title")
    provider_name = _provider_name_from(data, program_data)
    if function_name and provider_name:
        return f"{provider_name}/{function_name}"
    if function_name:
        return str(function_name)
    return None


def fetch_serverless_rows(
    client: ServerlessClient,
    statuses: list[str] | None,
    created_after_iso: str | None,
    limit: int,
    offset: int,
) -> list[dict[str, Any]]:
    """Fetch serverless jobs summary rows."""

    def _to_summary_rows(jobs: list[Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for job in jobs:
            data = job.raw_data or {}
            status = str(data.get("status", "Unknown"))
            sub_status = data.get("sub_status")
            out.append(
                {
                    "job_id": data.get("id", job.job_id),
                    "status": map_serverless_status(status, sub_status),
                    "sub_status": sub_status,
                    "created": data.get("created"),
                    "function": _display_function_name(data),
                }
            )
        return out

    if not statuses:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if created_after_iso:
            params["created_after"] = created_after_iso
        jobs = client.jobs(**params)
        return _to_summary_rows(jobs)

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for status in statuses:
        params: dict[str, Any] = {"limit": limit, "offset": offset, "status": status}
        if created_after_iso:
            params["created_after"] = created_after_iso
        jobs = client.jobs(**params)
        for row in _to_summary_rows(jobs):
            job_id = str(row.get("job_id"))
            if job_id in seen:
                continue
            seen.add(job_id)
            rows.append(row)
    return rows
