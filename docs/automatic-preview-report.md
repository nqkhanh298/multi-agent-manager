# Automatic target and Preview

The dashboard asks for one plain-language request. It submits `codex_auto`; a Codex selector chooses `web` for visual work and unspecified interfaces, and `python_cli` only for explicit terminal or script requests. The chosen target is recorded in the run report and events before the eight specialist roles begin. Older API engine values remain readable.

Both generated targets have a Preview tab. Browser apps run in the existing sandboxed iframe. Python CLI apps expose a Docker-backed terminal Preview: the user can supply up to 4096 characters of standard input, one response per line, then run `app.py` for at most ten seconds. Each click starts a fresh process; it is not a persistent terminal session. The API copies only `app.py` into a temporary workspace and returns bounded stdout/stderr. The sandbox has no network access.

This release supports standalone browser apps and single-file Python CLI programs. It does not infer arbitrary frameworks, start generated backend services, or preview native desktop apps. The original deterministic Task Manager demo remains available through the API for benchmarking.

## Verification

- Codex selected `web` for a graphical Tic Tac Toe request and `python_cli` for an explicit terminal calculator request using the signed-in local account.
- A Python program received standard input and returned `Hello, An` in the rebuilt Docker sandbox.
- Ruff passed; 56 Python tests, 3 frontend unit tests, 10 fixture browser tests, and the production dashboard build passed. The optional legacy live browser test was skipped.
