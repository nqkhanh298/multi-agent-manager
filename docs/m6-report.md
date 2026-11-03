# M6 hardening and benchmark report

Status: local deterministic release candidate verified on Windows 11, Ubuntu WSL2 and Docker Desktop.

## Delivered

- Migration `0003_hardening` adds per-run USD and time budgets, a worker heartbeat, and per-execution token/cost counters. Tool calls stop before exceeding the configured per-task step cap. Approval of an `increase_budget` request raises the run's USD cap after validating the amount.
- A worker records its heartbeat while a run is active. Recovery blocks a stale run, marks unresolved tool intents `UNKNOWN`, and skips duplicate jobs. It never replays an uncertain side effect. The worker also discovers committed `CREATED` runs after an API-to-Redis handoff failure.
- Model timeout and HTTP 429 errors become short sanitized errors. API task snapshots expose measured duration and recorded usage, while the dashboard shows duration on task nodes. Internal workspace and report filesystem paths are no longer returned in those snapshots.
- Fault-injection, budget, recovery and security tests; updated environment example and operating instructions.

## Setup verification

| Component | Observed |
| --- | --- |
| Windows WSL | Default Ubuntu distribution, WSL version 2 |
| Ubuntu | Python 3.14.4 in the project virtual environment; Docker server 29.9.2 |
| Docker Compose | PostgreSQL 17 and Redis 7 healthy on loopback ports |
| Database | Alembic `0003_hardening` at head; `alembic check` found no drift |
| Frontend | Windows Node.js 22.22.0 serves Vite on `http://localhost:5173/` |
| API | FastAPI on `http://localhost:8000/` |

Node/npm are not installed inside Ubuntu on this machine. The documented local workflow runs Vite on Windows and the Python API, worker and Docker sandboxes in WSL. This was verified end to end; WSL-hosted frontend development would require a separate Node installation.

## Benchmark evidence

| Check | Result | Measured elapsed / output | Artifact |
| --- | --- | --- | --- |
| M1 calculator | Pass, exit 0 | About 1.4 s; `2 passed` | `.local/workspaces/c2ab74bd-6681-4aed-866c-9158276e8c06/` |
| M2 fail then repair | Pass, exit 0 | About 3.5 s; first `1 failed, 2 passed`, then `3 passed` | `.local/runs/1845e64c-0ded-432c-878b-8020ae58fe11/` |
| M3 parallel task manager | Pass, exit 0 | About 10 s; 2,144 ms branch overlap; integration `4 passed` | `.local/m3-runs/ee01fb35-2080-45c5-adad-e4c3180a23cd/report.json` |
| M4 API/worker task manager | Pass, exit 0 | 13.52 s run duration from PostgreSQL; 31 ordered events, source ZIP | Run `e9b90334-0dca-4030-9ab5-59a635cf4400` |
| M5 live browser | Pass, exit 0 | 20.4 s final Playwright case; code, Git diff, tests and artifact visible | `.local/m5-dashboard.png` |
| M6 worker kill | Pass, exit 0 | About 1.6 s; run blocked, unresolved tool unknown, duplicate skipped | Run `514478f5-db86-4384-8656-ba47b16b31ec` |

`python -m scripts.verify_m1_sandbox` passed all seven Docker checks: file round trip, traversal and symlink rejection, non-root UID, host path isolation, network denial and command timeout. The M4 integration check also exercised auth, WebSocket replay, approval ownership, pause/resume and live sandbox cancellation. Existing M3 tests inject merge conflict and failed branch; M6 tests inject sandbox loss, model timeout, rate limit, stale heartbeat and tool-step exhaustion.

Final automated gates: `ruff check .` passed, `ruff format --check .` passed, Python `pytest -q` passed **43 tests**, frontend Vitest passed **3 tests**, production Vite build passed, npm audit found **0 vulnerabilities**. Playwright's four fixture-backed dashboard cases and the live browser case passed together (**5 passed**) against M6 services. The Vite build still warns about Monaco's large lazy-loaded chunk.

## Remaining limits and next work

- The API worker still runs the fixed deterministic M3 Task Manager workflow regardless of prompt. Real dynamic planning/coding in the platform is not delivered by M6. The M1/M2 provider adapters exist but have not made a billable live-model request in this verification.
- Token and USD counters are ready for a model-backed worker, but mock runs correctly record zero usage. Per-model price configuration and live accounting integration remain future work.
- A stale or crashed run is intentionally `BLOCKED`; an operator must reconcile unknown tool side effects before retrying. Automatic safe reconciliation and multi-worker lease ownership are not implemented.
- The fixed benchmark does not create approval requests itself. Budget increase approval can be recorded and applied, but automatic approval creation/resume after a budget stop is not yet part of the workflow.
- Docker Desktop/WSL2 provides a local demonstration boundary, not hardened isolation for hostile multi-tenant workloads.
