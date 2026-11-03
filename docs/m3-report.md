# M3 verification report

Status: local parallel-development workflow accepted with deterministic agents.

## Delivered

- DAG scheduler selects tasks whose dependencies are merged and caps concurrent
  coding tasks with `MAX_PARALLEL_TASKS` or `--max-parallel`.
- Backend and React frontend tasks use separate Git branches and worktrees.
- Backend tests and the frontend production build execute in role-specific,
  network-disabled Docker sandboxes.
- Successful branches merge sequentially into an integration branch. A failed
  task or merge conflict blocks the run; conflict paths are reported and QA is
  skipped.
- QA rebuilds the merged React app and runs backend and bundle integration
  checks. `report.json` records task timing, workspaces, merges, and QA output.
- The frontend build renders the React component to HTML. This catches missing
  runtime imports even when Vite compiles a bundle successfully.
- Frontend dependencies are locked in `docker/frontend/package-lock.json` and
  preinstalled in the frontend sandbox image. `npm audit` found no advisories
  when the lockfile was refreshed.

## Evidence on Ubuntu WSL2 with Docker Desktop

- Docker benchmark run `34ec01cc-1e8c-4937-860b-e0181276a632` completed.
  The backend branch passed 2 tests; the React/Vite production build succeeded
  with 23 modules transformed.
- The independent task intervals overlapped by 1354 ms. Both worktrees were
  distinct; both branches merged in order, with merge commits recorded.
- QA rebuilt the merged React frontend and the Python integration suite passed
  4 tests in 0.01s. Both frontend checks reported `React render smoke passed`.
- Headless Chrome displayed the task manager heading, input, and button at
  `http://localhost:4173/` after the missing React import was fixed.
- The new render check rejected the previous broken app with
  `React is not defined`, proving the regression is caught before acceptance.
- The repository test suite passed 32 tests; Ruff lint and format checks passed.
- Automated tests cover parallel overlap, the single-worker limit, dependency
  ordering, merge conflict blocking, and failed-branch blocking.

## Limits

- Agents are deterministic mocks. M3 exercises scheduling, sandboxed execution,
  merging, and verification without a live model request.
- The React demo manages tasks in browser state. Connecting it to a backend API
  and building the platform dashboard are later milestones.
- M3 run state is a local JSON report. Durable distributed scheduling, leases,
  cancellation, and restart recovery belong to the backend milestone.
