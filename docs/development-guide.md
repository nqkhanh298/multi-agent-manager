# Detailed local development guide

This repository contains all six local milestones described in
`MULTI_AGENT_CODING_PLATFORM_WINDOWS.md`. M1 runs one tool-using coding agent in
Docker. M2 adds a validated task DAG, Coordinator, QA, a bounded repair loop and
durable local LangGraph checkpoints. M3 schedules independent backend and React
frontend tasks in separate Git worktrees, merges them in order, and runs
integration QA. M4 adds a PostgreSQL-backed FastAPI control plane, Redis worker
queue, event stream, run controls and artifact downloads. M5 adds a React
dashboard with a live workflow graph, code and diff viewers, event and test
output, approval decisions and browser tests. M6 adds per-run budgets, worker
heartbeat recovery, fault injection, security verification and a benchmark
report. This is still a deterministic local demo, not a general prompt-to-app
service.

## Requirements

- Windows 11 with WSL2 Ubuntu and Docker Desktop configured for Linux containers.
- Run the repository from the WSL Linux filesystem, for example `~/projects/ai-coding-platform`.
- Python 3.11+ in WSL. Node.js 20.19+ and npm are required for the M5 dashboard.
- Docker daemon accessible from WSL. Do not run the agent on the Windows host.

## Build and run in WSL

Enable Ubuntu WSL integration in Docker Desktop. Clone or copy this repository
into the Ubuntu Linux filesystem before running the commands below, for example
at `~/projects/multi-agent-manager`. Do not run the agent from `/mnt/c/...`.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
docker build -f docker/sandbox.Dockerfile -t ai-coding-m1:local .
docker build -f docker/frontend.Dockerfile -t ai-coding-m3-frontend:local .
pytest -q
ruff check .
ruff format --check .
python -m coding_platform.cli demo
python -m scripts.verify_m1_sandbox
python -m coding_platform.cli m2-demo
python -m coding_platform.cli m3-demo
```

`requirements.lock` records the exact resolved dependency versions from the
verified Ubuntu environment. For a reproducible reinstall, install it first,
then run `pip install -e . --no-deps`.

The M2 demo deliberately writes a faulty `divide` function. QA first reports
one failed test; the Developer repairs the file and QA then reports three passed
tests. `--max-retries 0` demonstrates a blocked run without repair.

To demonstrate checkpoint recovery across separate processes:

```bash
python -m coding_platform.cli m2-demo --pause-after implement
python -m coding_platform.cli m2-resume --run-id <id-from-first-command>
```

M2 stores LangGraph checkpoints and an idempotent tool-call journal in
`.local/runs/<run-id>/`. A tool call left in an uncertain `started` state blocks
automatic replay pending reconciliation. SQLite is the local M2 development
store; the M4 platform backend stores server state in PostgreSQL.

The M3 demo uses deterministic agents to create a Python task backend and a
React/Vite frontend. Independent tasks execute concurrently in separate Git
worktrees, each with its own sandbox check. The frontend build also renders the
app to HTML to catch runtime errors that a successful bundle alone can miss.
Completed branches merge into an integration branch one at a time. QA rebuilds
the merged frontend and runs the
Python integration suite. The CLI prints a report whose run directory is
`.local/m3-runs/<run-id>/`; `report.json` records task status, worktrees, merge
commits, parallel overlap, and integration output. Use `--max-parallel 1` to
run the independent tasks sequentially. Merge conflicts and failed tasks block
the run and skip QA.

## M4 backend in WSL

Start infrastructure and migrate an empty PostgreSQL database:

```bash
docker compose -f docker/compose.yaml up -d --wait postgres redis
alembic upgrade head
python -m apps.api.bootstrap --name local
```

The bootstrap command prints a random API token once. Keep it private. Start
the API and worker in separate WSL terminals:

```bash
uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
python -m apps.worker.main
```

Open `http://localhost:8000/docs` and use **Authorize** with the token. Create
a project, then a run. The worker executes the fixed M3 task-manager benchmark;
`GET /api/runs/{id}` shows status, and the task, event, tool-call and artifact
endpoints show its results. WebSocket `/ws/runs/{id}` accepts a bearer header or
an initial JSON message `{"token":"..."}`. Run the full integration benchmark
with `python -m scripts.verify_m4` while the persistent worker is stopped;
the script processes its own queued jobs.

M4 data is stored in PostgreSQL and `.local/platform/`. Only the API and worker
have database credentials; generated code runs in network-disabled Docker
sandboxes.

## M5 visual dashboard on Windows

Keep the M4 API and worker running in WSL. In a Windows terminal at the repository
root, run:

```powershell
cd apps/web
npm ci
npm run dev
```

Open `http://localhost:5173/`. Paste the local API token printed by
`python -m apps.api.bootstrap --name local`. The bootstrap command does not
save the token; if it was lost, create another local user with a different name.

Create a project, enter a prompt and start a run. The current worker executes
the fixed M3 Task Manager workflow regardless of prompt; the dashboard labels
this behavior. Its graph, statuses, events, source files, Git diff, test output,
and source ZIP are fetched from the M4 API. The editor and event/terminal views
are read-only. WebSocket events replay after reconnect; REST polling fills in
state when the socket is unavailable. Approval controls appear when the API has
a pending approval.

To verify the frontend, run `npm run build`, `npm run test`, and
`npm run test:e2e` from `apps/web`. Playwright uses local Chrome on Windows.
The optional live browser case requires `M5_LIVE_TOKEN` and the running M4
services; without it, that case is skipped. See `docs/m5-report.md` for the
verified local run and remaining limits.

## M6 hardening and verification

After updating the code in WSL, apply the new schema before restarting the API
and worker:

```bash
alembic upgrade head
alembic check
```

Each new run records a USD cap (default 5), a wall-clock cap (default 1800
seconds), and a per-task tool-call cap (default 20). Set `MAX_RUN_USD`,
`MAX_RUN_SECONDS`, or `MAX_AGENT_STEPS` in the API/worker environment to change
the defaults. The worker heartbeats every five seconds. If a run loses its
heartbeat, recovery marks it `BLOCKED` and in-flight tool calls `UNKNOWN` for
manual reconciliation; it does not repeat those tool calls. The stale threshold
is `WORKER_STALE_SECONDS` (default 30). The deterministic M3 agents make no
billable model calls, so their recorded model spend and token counts are zero.

Verify from WSL with:

```bash
ruff check .
ruff format --check .
pytest -q
python -m scripts.verify_m1_sandbox
```

Stop the persistent worker before running the following integration checks;
each test controls its own queue worker:

```bash
python -m scripts.verify_m4
python -m scripts.verify_m6_faults
```

The M6 fault test kills its own worker after a durable tool intent, then checks
that the run blocks, the tool outcome is unknown, and duplicate delivery is
skipped. See `docs/m6-report.md` for benchmark results, setup verification and
remaining risks.

To use live model planning and coding, set `OPENAI_API_KEY` and run
`python -m coding_platform.cli m2-demo --provider openai --model "$LLM_MODEL"`.
This makes billable requests. The fixed calculator workflow accepts only a
`T1 backend_dev -> T2 qa` plan; general DAG scheduling belongs to M3.
The adapter uses [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
and the local workflow uses [LangGraph checkpoints](https://docs.langchain.com/oss/python/langgraph/checkpointers).

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
- M2 uses deterministic mock agents for its repeatable fail/repair benchmark.
  The live model path is wired and unit tested with simulated responses, but
  has not made a billable API request.
- M3 provides local DAG scheduling and merge verification. M4 exposes this
  fixed mock workflow through an API and worker; M5 visualizes it. A general
  live-model workflow remains future work.
- M6 records task duration and has counters for model tokens and cost; the fixed
  mock benchmark records zero model usage. The approval UI
  is verified with a browser fixture; the fixed benchmark does not create an
  approval request on its own.
- M1 audit remains JSONL. M2 adds a durable SQLite tool journal but deliberately
  blocks uncertain side effects rather than guessing whether they completed.

## Test evidence

See `docs/m1-report.md`, `docs/m2-report.md`, `docs/m3-report.md`,
`docs/m4-report.md`, `docs/m5-report.md`, and `docs/m6-report.md` for evidence
and limitations.
