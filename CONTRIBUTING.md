# Contributing

Thanks for helping improve the local platform prototype.

## Before you start

Read the [README](README.md) and [development guide](docs/development-guide.md). The API/worker currently run a fixed deterministic Task Manager workflow. A change that enables general prompt-to-app generation needs its own design, budget accounting, security review, and end-to-end tests; do not describe the current benchmark as a live model workflow.

## Development setup

Run the Python agent, API, worker, and Docker sandbox from the Ubuntu WSL2 Linux filesystem. Run the dashboard with Node.js 22+ in WSL or a synchronized Windows checkout. See the README for installation and local service commands.

Before opening a pull request, run:

```bash
ruff check .
ruff format --check .
pytest -q
```

From `apps/web`, run:

```bash
npm ci
npm run build
npm run test
npm run test:e2e
```

The fixture-backed browser tests work without a live backend. Sandbox and full API/worker checks need the local Docker infrastructure; their commands and prerequisites are in the development guide.

## Pull requests

- Keep changes focused and explain the behavior, verification, and known limits.
- Add tests when behavior or a safety boundary changes. Prefer small tests for permissions, recovery, state transitions, and sandbox behavior.
- For database changes, include an Alembic migration and verify `alembic check`.
- Do not commit `.env`, API tokens, model credentials, generated `.local/` data, `node_modules`, or personal editor settings.
- Keep screenshots and documentation honest about which results come from a live local run and which use test fixtures.

By contributing, you agree that your contributions are licensed under the repository's [MIT License](LICENSE).
