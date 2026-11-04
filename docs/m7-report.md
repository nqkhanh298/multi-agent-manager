# M7: Codex role sessions (local alpha)

## Implemented

- The dashboard connects a local platform user to ChatGPT using the Codex app-server browser or device-code login flow. The platform API token remains separate from ChatGPT authentication.
- Each platform user has a separate, ignored `CODEX_HOME` under `.local/platform/codex-accounts/<user-id>`. Credentials stay with the Codex process and are never sent to the browser or Docker sandbox.
- The Codex engine runs eight distinct sessions: Coordinator, Researcher, Architect, Designer, Developer, QA, Writer, and Release. Each receives its own repository skill from `.agents/skills/<role>/SKILL.md` and a restricted, read-only context directory.
- Developer returns structured `app.py` and `test_app.py` source. The worker writes these through the existing Docker sandbox. QA runs pytest in that sandbox. Notes and source are packaged into the existing ZIP artifact on success.
- The original Task Manager benchmark remains selectable as the `demo` engine for offline verification.

## Verified locally

- Codex CLI installed in Ubuntu WSL and app-server `initialize` plus `account/read` returned a valid unauthenticated response. No user credentials were read or copied.
- PostgreSQL/Redis started, Alembic reached `0004_codex_engine`, and authenticated API `/api/codex/account` returned the expected disconnected state.
- Python `ruff check`, `ruff format --check`, and `pytest -q` passed: 46 tests.
- Dashboard production build and three Vitest tests passed. Playwright passed five fixture-backed cases; the optional live legacy case was skipped without `M5_LIVE_TOKEN`.

## Current limits

- A live Codex run needs the user to authorize ChatGPT from the dashboard. This was not completed during implementation, so no end-to-end Codex result is claimed yet.
- The role DAG is fixed and sequential. Only the generated Python command-line source varies with the prompt; there is no desktop GUI or Windows executable packaging yet.
- Codex role turns are read-only and cannot directly edit files. Generated Python is applied and tested by the Docker worker. QA reports failures; automated repair after a failing Codex run is still future work.
- ChatGPT-plan usage is not priced in USD by the platform. The run's USD fields are unset; Codex/ChatGPT account limits still govern model usage.
- This is a local development integration. Codex app-server authentication is documented for local/open-source apps; production account integration should use the official Sign in with ChatGPT flow and appropriate hosting/security review.
