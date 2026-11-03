# M2 verification report

Status: deterministic local workflow accepted; live model path not yet verified
against a billable API.

## Delivered

- Pydantic task/plan schemas enforce unique task IDs, known roles, valid
  dependencies, no cycles, maximum task count and depth.
- Mock Coordinator emits a two-task DAG: implementation, then QA.
- LangGraph nodes plan, validate, implement, QA, repair, complete and block.
- SQLite LangGraph checkpointer persists each graph step under a run thread ID.
- SQLite tool journal records intent and result by tool call ID. Completed calls
  replay their result; unknown outcomes stop automatic replay.
- CLI commands `m2-demo`, `m2-resume`, `--pause-after` and `--max-retries`.
- Optional OpenAI Coordinator and Developer use structured JSON output for the
  fixed calculator workflow. Their request/response handling has a mocked HTTP
  test; no billable request has been made.
- `requirements.lock` pins all 46 resolved packages; the sandbox base image is
  pinned by digest.

## Evidence on Ubuntu WSL2 with Docker Desktop

- Unit tests: 27 passed in 0.27s, including worker crash after tool intent.
- `m2-demo`: exit 0, run `0d51e2e0-a033-4dc6-88fe-44692feaa63b`:
  first pytest result `1 failed, 2 passed`; after one repair,
  `3 passed in 0.01s`.
- Two-process recovery: run `8fdda3ea-16fa-483d-8578-bf76bd006adb` paused
  after implementation, then `m2-resume` completed with the same fail → fix →
  pass sequence and one repair.
- `m2-demo --max-retries 0`: exit 1 and status BLOCKED after first failed test;
  no repair executed.
- Final benchmark after model adapter wiring: run
  `9c495ec2-ba6c-472e-b3f6-e7339719147e` completed after one repair,
  `1 failed, 2 passed` → `3 passed`.
- Final two-process recovery: run `742b541b-7ca2-4fac-bdbc-c5591e3db891`
  paused after implementation and resumed to COMPLETED with fail → pass.

## Limits

- Coordinator and Developer are deterministic mocks in the benchmark. The live
  OpenAI path is available but unverified against the actual API and model.
- SQLite is for local development; the M4 backend will use PostgreSQL and a
  worker queue.
- An uncertain tool side effect is blocked for manual reconciliation. Automatic
  reconciliation of file hashes and sandbox processes is future work.
