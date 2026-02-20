# qiskit-serverless-console

```
+------------------------------------------------------------------------------+
| qiskit-serverless-jobs-watch                                                 |
|                                                                              |
|  refresh: 1s   mode: table/json   runtime: background poller               |
|  tree: rich Tree (serverless job -> runtime jobs)                           |
|  missing fields: rich Spinner placeholders                                  |
+------------------------------------------------------------------------------+
```

Standalone console project to watch Qiskit Serverless jobs and related Qiskit Runtime jobs.

## Install

```bash
cd qiskit-serverless-console
pip install -r requirements.txt
pip install -e .
```

This installs:

`qiskit-serverless-jobs-watch`

## Environment Variables

The CLI reads auth and endpoints from environment variables (no auth/url flags).

Serverless + Runtime shared auth:
- `QISKIT_IBM_TOKEN` (required)
- `QISKIT_IBM_INSTANCE` (required)

Serverless host:
- `ENV_GATEWAY_PROVIDER_HOST` (optional)
- Default when missing: `https://qiskit-serverless.quantum.ibm.com`

Runtime connection:
- `QISKIT_IBM_URL` (optional, default: `https://cloud.ibm.com`)
- `QISKIT_IBM_CHANNEL` (optional, default: `ibm_quantum_platform`)

## Staging

For staging, set:
- `QISKIT_IBM_URL=https://test.cloud.ibm.com`
- `ENV_GATEWAY_PROVIDER_HOST=https://qiskit-serverless-dev.quantum.ibm.com`

## Usage

```bash
qiskit-serverless-jobs-watch
```

Available CLI options (only non-env configuration):
- `--job-id`
- `--function`
- `--status` (repeatable)
- `--last-hours` (default: `2.0`)
- `--limit` (default: `50`)
- `--offset` (default: `0`)
- `--interval` (default: `1`)
- `--json`
- `--no-color`

Examples:

```bash
qiskit-serverless-jobs-watch --status RUNNING --status QUEUED
qiskit-serverless-jobs-watch --last-hours 6 --interval 2
qiskit-serverless-jobs-watch --json
```

## Behavior

- Refreshes continuously until `Ctrl+C`.
- Shows newest jobs at the top (sorted by `created` descending).
- Displays runtime jobs as child lines under each serverless job.
- Uses a background thread to refresh runtime status cache.
- Stops polling terminal runtime jobs.
- If status/backend (or other key display fields) is missing, shows an animated spinner placeholder.
