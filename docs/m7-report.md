# M7: Codex role sessions (local alpha)

## Implemented

- The dashboard connects a local platform user to ChatGPT using the Codex app-server browser or device-code login flow. The platform API token remains separate from ChatGPT authentication.
- Each platform user has a separate, ignored `CODEX_HOME` under `.local/platform/codex-accounts/<user-id>`. Credentials stay with the Codex process and are never sent to the browser or Docker sandbox.
- The Codex engine runs eight distinct sessions: Coordinator, Researcher, Architect, Designer, Developer, QA, Writer, and Release. Each receives its own repository skill from `.agents/skills/<role>/SKILL.md` and a read-only working directory.
- Developer returns structured `app.py` and `test_app.py` source. The worker writes these through the existing Docker sandbox. QA runs pytest in that sandbox. Notes and source are packaged into the existing ZIP artifact on success.
- The original Task Manager benchmark remains selectable as the `demo` engine for offline verification.

## Verified locally

- Codex CLI installed in Ubuntu WSL and app-server `initialize` plus `account/read` returned a valid unauthenticated response. No user credentials were read or copied.
- PostgreSQL/Redis started, Alembic reached `0004_codex_engine`, and authenticated API `/api/codex/account` returned the expected disconnected state.
- Python `ruff check`, `ruff format --check`, and `pytest -q` passed: 52 tests.
- After ChatGPT sign-in, a live Coordinator turn returned the expected diagnostic response. This caught and verified the fix for an app-server protocol change: `readOnly.access` is rejected by current Codex, so turns now use the supported read-only sandbox policy.
- A live Codex turn was interrupted and reported `CANCELLED`. The dashboard now shows the requested stop state until the worker acknowledges it, and the active task leaves `RUNNING` on pause or cancellation. The current activity and recent role steps are shown in the progress panel.
- Finished projects can now be deleted through a confirmation dialog. The API checks ownership, rejects active runs, removes dependent records, then removes generated run and artifact directories. A cleanup warning is returned if local file deletion fails.
- The workflow now lays out dependencies from left to right, keeps cards readable with horizontal scrolling, follows the active task, and uses role colors, stage labels, arrowed edges, and reduced-motion-aware animations.
- Dashboard production build, three Vitest tests and eight fixture-backed Playwright cases passed after the control and activity changes.

## Current limits

- A complete eight-role Codex run is not yet verified; the user's first run stopped at Coordinator because the old sandbox policy was rejected before model execution.
- The role DAG is fixed and sequential. Only the generated Python command-line source varies with the prompt; there is no desktop GUI or Windows executable packaging yet.
- Codex role turns use the current app-server read-only sandbox with network access disabled and cannot directly edit files. This sandbox does not restrict reads to the project directory. Generated Python is applied and tested by the Docker worker. QA reports failures; automated repair after a failing Codex run is still future work.
- ChatGPT-plan usage is not priced in USD by the platform. The run's USD fields are unset; Codex/ChatGPT account limits still govern model usage.
- This is a local development integration. Codex app-server authentication is documented for local/open-source apps; production account integration should use the official Sign in with ChatGPT flow and appropriate hosting/security review.
