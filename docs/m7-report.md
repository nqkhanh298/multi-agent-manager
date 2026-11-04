# M7: Codex role sessions (local alpha)

## Implemented

- The dashboard connects a local platform user to ChatGPT using the Codex app-server browser or device-code login flow. The platform API token remains separate from ChatGPT authentication.
- Each platform user has a separate, ignored `CODEX_HOME` under `.local/platform/codex-accounts/<user-id>`. Credentials stay with the Codex process and are never sent to the browser or Docker sandbox.
- The Codex engine runs eight distinct sessions: Coordinator, Researcher, Architect, Designer, Developer, QA, Writer, and Release. Each receives its own repository skill from `.agents/skills/<role>/SKILL.md` and a read-only working directory.
- Codex Python returns `app.py` and `test_app.py`; Codex Web returns `index.html`, `styles.css`, `app.js` and `test.js`. The worker writes these through Docker. QA runs pytest or Node's built-in test runner in Docker, respectively. Notes and source are packaged into a ZIP on success.
- The dashboard offers an interactive Preview tab for Codex Web runs. It loads files through the authenticated API and runs the app in an opaque-origin iframe with a restrictive content security policy.
- The original Task Manager benchmark remains selectable as the `demo` engine for offline verification.

## Verified locally

- Codex CLI installed in Ubuntu WSL and app-server `initialize` plus `account/read` returned a valid unauthenticated response. No user credentials were read or copied.
- PostgreSQL/Redis started, Alembic reached `0004_codex_engine`, and authenticated API `/api/codex/account` returned the expected disconnected state.
- Python `ruff check`, `ruff format --check`, and `pytest -q` passed: 53 tests.
- After ChatGPT sign-in, a live Coordinator turn returned the expected diagnostic response. This caught and verified the fix for an app-server protocol change: `readOnly.access` is rejected by current Codex, so turns now use the supported read-only sandbox policy.
- A live Codex turn was interrupted and reported `CANCELLED`. The dashboard now shows the requested stop state until the worker acknowledges it, and the active task leaves `RUNNING` on pause or cancellation. The current activity and recent role steps are shown in the progress panel.
- Finished projects can now be deleted through a confirmation dialog. The API checks ownership, rejects active runs, removes dependent records, then removes generated run and artifact directories. A cleanup warning is returned if local file deletion fails.
- The workflow now lays out dependencies from left to right, keeps cards readable with horizontal scrolling, follows the active task, and uses role colors, stage labels, arrowed edges, and reduced-motion-aware animations.
- Dashboard production build, three Vitest tests and nine fixture-backed Playwright cases passed. A real Codex Developer turn produced a standalone web game; after aligning the test filename with Node 22 module detection, its three generated tests passed in Docker. A separate eight-role web smoke run completed, with five generated Node tests passing in Docker.

## Current limits

- The eight-role web smoke run used the Codex runner directly; it did not exercise the database queue or artifact download. The dashboard preview was exercised with fixture files. A user-created run through the full HTTP and browser path still needs observation.
- The role DAG is fixed and sequential. Codex Web supports standalone browser apps without backend services or external dependencies. Native desktop GUI and Windows executable packaging remain future work.
- Codex role turns use the current app-server read-only sandbox with network access disabled and cannot directly edit files. This sandbox does not restrict reads to the project directory. Generated Python is applied and tested by the Docker worker. QA reports failures; automated repair after a failing Codex run is still future work.
- ChatGPT-plan usage is not priced in USD by the platform. The run's USD fields are unset; Codex/ChatGPT account limits still govern model usage.
- This is a local development integration. Codex app-server authentication is documented for local/open-source apps; production account integration should use the official Sign in with ChatGPT flow and appropriate hosting/security review.
