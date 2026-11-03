# M4 verification report

Status: local platform backend accepted with deterministic M3 agents.

## Delivered

- FastAPI control plane with bearer-token authentication and owner-scoped
  project, run, task, event, approval, tool-call and artifact endpoints.
- PostgreSQL schema with Alembic migrations for users, projects, runs, tasks,
  executions, tool-call intents/results, ordered events, outbox, approvals and
  artifacts. Event sequence assignment locks the run row.
- Redis job queue with a processing list for redelivery and a worker that runs
  the M3 worktree flow. The worker publishes committed outbox events to Redis.
  WebSocket clients replay ordered events from PostgreSQL after reconnect.
- Pause and resume at task-batch boundaries; cancel removes an active Docker
  sandbox container. Tool calls have unique idempotency keys, and an uncertain
  outcome is recorded as `UNKNOWN` instead of silently replayed.
- A source ZIP is built after QA succeeds. It excludes Git internals, generated
  dependencies, `.env` files, private keys and symlinks; downloads verify the
  stored SHA-256 checksum and project ownership.
- Docker Compose starts local PostgreSQL and Redis on loopback interfaces.

## Evidence on Ubuntu WSL2 with Docker Desktop

- PostgreSQL and Redis health checks passed. `alembic upgrade head` reached
  `0002_tool_journal`, and `alembic check` detected no schema drift.
- Repository suite: 35 tests passed, including owner scoping, ordered event
  storage, source ZIP exclusions, M3 pause/resume, and existing M1-M3 checks.
- End-to-end benchmark run `b66271c8-49ae-4b89-bc1b-858390074e65` completed
  through API -> Redis -> worker -> Docker -> PostgreSQL. It produced 31 ordered
  events and a downloadable source ZIP. The benchmark also verified WebSocket
  replay, another user's 404 responses, approval decision, queued and mid-run
  pause/resume, queued cancellation, cancellation through the API while a run
  was active, and direct live sandbox cancellation.
- API documentation responded at `http://localhost:8000/docs`.

## Limits

- M4 still uses deterministic agents and the fixed M3 task-manager workflow.
  The live model path remains unverified against a billable model API.
- The visual platform dashboard is M5. Swagger UI at `/docs` is an API explorer.
- The local worker is single-process. A crash during a tool side effect leaves
  a run needing reconciliation; stale lease recovery and stronger multi-worker
  scheduling are hardening work. Pause waits for the current task batch to end.
- Docker Desktop and WSL2 are suitable for this local demo, not a strong
  isolation boundary for hostile multi-tenant code.
