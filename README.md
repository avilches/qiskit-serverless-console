# qiskit-serverless-console

Standalone console project to watch Qiskit Serverless jobs and related Qiskit Runtime jobs.

Features:
- Show status in realtime (polling data every 1sec)
- Show runtime jobs as children
- Press L to see the logs
- Press S to stop a job (serverless or runtime, with confirmation modal)

![Screenshot](screenshot-1.png)

## Install

```bash
pip install -r requirements.txt
pip install -e .
```

## Run

```bash
export QISKIT_IBM_TOKEN=<your token>
export QISKIT_IBM_INSTANCE=<your runtime crn instance>
qiskit-serverless-jobs-watch
```

## Environment Variables

| Name                         | Mandatory | Description                                                               |
|------------------------------|-----------|---------------------------------------------------------------------------|
| `QISKIT_IBM_TOKEN`           | Yes       | IBM Cloud Api token                                                       |
| `QISKIT_IBM_INSTANCE`        | Yes       | IBM Cloud CRN instance                                                    |
| `ENV_GATEWAY_PROVIDER_HOST`  | -         | Serverless API host. Default: `https://qiskit-serverless.quantum.ibm.com` |
| `ENV_GATEWAY_PROVIDER_TOKEN` | -         | Serverless API token. Falls back to `QISKIT_IBM_TOKEN`                    |
| `QISKIT_IBM_URL`             | -         | Runtime API host. Default: `https://cloud.ibm.com`                        |
| `QISKIT_IBM_CHANNEL`         | -         | Runtime channel. Default: `ibm_quantum_platform`                          |

## Stagingx

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
- `--limit` (default: `50`)
- `--offset` (default: `0`)
- `--interval` (default: `1`)
- `--json`
- `--no-color`

Examples:

```bash
qiskit-serverless-jobs-watch --status RUNNING --status QUEUED
qiskit-serverless-jobs-watch --json
```
