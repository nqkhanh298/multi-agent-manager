# Multi-Agent AI Coding Platform — M1

This repository contains the first verified vertical slice described in
`MULTI_AGENT_CODING_PLATFORM_WINDOWS.md`: one tool-using coding agent, an offline
mock provider, and a Docker sandbox that writes a Python calculator and runs pytest.
It is not yet the full multi-agent platform or the dashboard.

## Requirements

- Windows 11 with WSL2 Ubuntu and Docker Desktop configured for Linux containers.
- Run the repository from the WSL Linux filesystem, for example `~/projects/ai-coding-platform`.
- Python 3.11+ in WSL. The host-side unit tests also work on Python 3.9.
- Docker daemon accessible from WSL. Do not run the agent on the Windows host.

## Build and run in WSL

On this machine WSL2 Ubuntu and Docker Desktop are installed, and Ubuntu WSL
integration is enabled. Copy this repository into `~/projects/ai-coding-platform`
in Ubuntu before running the commands below. Do not run the demo from `/mnt/c/...`.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
docker build -f docker/sandbox.Dockerfile -t ai-coding-m1:local .
pytest -q
ruff check .
ruff format --check .
python -m coding_platform.cli demo
python -m scripts.verify_m1_sandbox
```

For a real model, set `OPENAI_API_KEY` in the WSL process environment, choose a
tool-capable model in `LLM_MODEL`, then run
`python -m coding_platform.cli demo --provider openai --model "$LLM_MODEL"`.
This makes billable API requests; the mock command above needs no key or network.
The API key stays in the manager process and is never included in the Docker
container environment or audit log. The adapter follows the official
[OpenAI Responses function-calling protocol](https://developers.openai.com/api/docs/guides/function-calling).

The demo prints the run ID, workspace path and tool results. Its generated files
are under `.local/workspaces/<run-id>/`; audit events are under
`.local/runs/<run-id>/audit.jsonl`. The `run-pytest` result must have exit code 0.

The Docker runner uses no network, a non-root UID, read-only root filesystem,
minimal capabilities, no privilege escalation, CPU/memory/PID limits, bounded
tool output and timeouts. Only the per-run workspace is mounted. Generated code
and pytest run inside the container. The manager refuses to start on Windows.

## Current limits

- The mock provider follows a fixed calculator script; it is for testing the
  tool pipeline. The real provider adapter is implemented but its live path
  needs an API key and a billable sandbox run for end-to-end verification.
- Docker Desktop/WSL2 is suitable for a local demo, not a strong production
  isolation boundary for hostile multi-tenant workloads.
- There is no database, checkpointing, scheduler, API or UI yet. Those are later milestones.
- The current audit log is local JSONL and is not crash-safe/idempotent for
  side effects. Durable tool-call storage is planned for later milestones.

## Test evidence

See `docs/m1-report.md` for the latest environment check and test results.
