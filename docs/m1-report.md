# M1 verification report

Status: M1 mock-provider vertical slice accepted. Real-model execution remains
unverified because it requires billable API usage and a user-provided key.

## Environment observed on 2026-11-03

- Windows host `python --version`: 3.9.13.
- Windows host `node --version`: v22.22.0.
- `wsl --status`: exit code 1, no usable status reported.
- `wsl --list --verbose`: exit code 1 and usage text, no distro listed.
- `docker version`: command not found.
- `python -m pytest --version`: 8.4.2.
- Initial `python -m pytest -q`: 14 passed in 0.11s (Windows host,
  trusted unit tests only).
- `ruff check coding_platform docker tests --no-cache`: passed.
- `ruff format --check coding_platform docker tests`: passed.
- `python -m coding_platform.cli demo`: correctly refused to run on Windows host.
- `wsl --install -d Ubuntu`: reported WSL and Ubuntu installed; Windows says reboot required.
- `winget install --id Docker.DockerDesktop ...`: reported successfully installed.
- After installation, `wsl --status` still reports the WSL optional component is
  unavailable until Windows restarts. Docker/Ubuntu integration is not yet verified.

## Verification after restart

- WSL2 Ubuntu and Docker Desktop Engine 29.9.2 are running.
- Docker Desktop WSL integration for Ubuntu is enabled.
- `docker build -f docker/sandbox.Dockerfile -t ai-coding-m1:local .`: exit 0.
- `python3 -m coding_platform.cli demo` from Ubuntu ext4: exit 0, run ID
  `2169a6c0-e7de-4f9f-a18d-23a9f144fbd1`.
- Generated `calculator.py` and `test_calculator.py` exist under that run's
  `.local/workspaces/` directory; both were created by sandbox tool calls.
- `run-pytest` tool result: exit code 0, `2 passed in 0.01s`.
- Audit contains started/finished events for both writes and pytest, followed
  by `agent.finished`.
- `python3 -m scripts.verify_m1_sandbox`: exit 0; 7/7 checks true for file
  round trip, traversal, symlink, non-root UID, host path isolation, network
  block and command timeout.
- Final WSL unit suite: 17 passed in 0.03s; Ruff lint and format checks passed.
- After adding `.dockerignore` and strict tool-result validation, rebuilt the
  image and reran the demo: run ID `a77685b0-aa89-41c7-974a-a6d4a7738487`,
  `2 passed in 0.01s`, exit code 0.

## Remaining limits and later work

- Live OpenAI adapter has a mocked round-trip unit test but has not made a
  billable API request. The mock provider uses a fixed calculator script.
- Docker Desktop/WSL2 is a local-demo isolation level, not production-grade
  protection against hostile multi-tenant code.
- Audit is local JSONL; durable idempotent tool storage belongs to later
  milestones.
