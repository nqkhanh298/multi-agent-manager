import sqlite3

import pytest
from pydantic import ValidationError

from coding_platform.contracts import ToolCall, ToolResult
from coding_platform.journal import ToolJournal, UncertainToolCall
from coding_platform.m2 import M2Runner
from coding_platform.plan import Plan


def task(task_id, depends_on=None):
    return {
        "id": task_id,
        "title": "Valid task",
        "agent": "backend_dev",
        "depends_on": depends_on or [],
        "acceptance_criteria": ["done"],
    }


@pytest.mark.parametrize(
    "tasks",
    [
        [task("T1"), task("T1")],
        [task("T1", ["T2"]), task("T2", ["T1"])],
        [task("T1", ["T9"])],
        [task("T1", ["T1"])],
    ],
)
def test_plan_rejects_invalid_dag(tasks):
    with pytest.raises(ValidationError):
        Plan.model_validate({"tasks": tasks})


def test_plan_accepts_valid_dag():
    plan = Plan.model_validate({"tasks": [task("T1"), task("T2", ["T1"])]})
    assert plan.tasks[1].depends_on == ["T1"]


class FakeSandbox:
    def __init__(self, always_fail=False):
        self.calls = []
        self.always_fail = always_fail

    def execute(self, call):
        self.calls.append(call)
        if call.name == "run_command":
            attempt = len([item for item in self.calls if item.name == "run_command"]) - 1
            failed = self.always_fail or attempt == 0
            return ToolResult(
                call.id,
                not failed,
                int(failed),
                "FAILED test_fractional_division" if failed else "3 passed",
            )
        return ToolResult(call.id, True, 0, changed_files=[call.arguments["path"]])


def test_fail_repair_pass_and_checkpoint_resume(tmp_path):
    sandbox = FakeSandbox()

    def factory(workspace):
        return sandbox

    first_runner = M2Runner(tmp_path, sandbox_factory=factory)
    paused = first_runner.run("calculator", interrupt_after=["implement"])
    run_id = paused["run_id"]
    assert [call.name for call in sandbox.calls] == ["write_file", "write_file"]
    assert first_runner.snapshot(run_id)["next"] == ["qa"]

    resumed = M2Runner(tmp_path, sandbox_factory=factory).resume(run_id)
    assert resumed["status"] == "COMPLETED"
    assert [report["passed"] for report in resumed["test_history"]] == [False, True]
    assert resumed["repair_attempts"] == 1
    assert len([call for call in sandbox.calls if call.name == "write_file"]) == 3
    assert M2Runner(tmp_path, sandbox_factory=factory).resume(run_id)["status"] == "COMPLETED"


def test_retry_budget_blocks(tmp_path):
    sandbox = FakeSandbox(always_fail=True)
    state = M2Runner(tmp_path, max_retries=1, sandbox_factory=lambda workspace: sandbox).run(
        "calculator"
    )
    assert state["status"] == "BLOCKED"
    assert state["repair_attempts"] == 1
    assert len(state["test_history"]) == 2


def test_tool_journal_replays_completed_and_blocks_uncertain(tmp_path):
    sandbox = FakeSandbox()
    journal = ToolJournal(tmp_path / "calls.sqlite", sandbox)
    call = ToolCall("id-1", "write_file", {"path": "a.txt", "content": "hello"})
    assert journal.execute(call).ok
    assert journal.execute(call).ok
    assert len(sandbox.calls) == 1
    with pytest.raises(UncertainToolCall, match="different arguments"):
        journal.execute(ToolCall("id-1", "write_file", {"path": "b.txt"}))

    with sqlite3.connect(tmp_path / "calls.sqlite") as db:
        db.execute(
            "INSERT INTO tool_calls (id, name, args_json, status) "
            "VALUES ('unknown', 'read_file', '{}', 'started')"
        )
    with pytest.raises(UncertainToolCall, match="outcome unknown"):
        journal.execute(ToolCall("unknown", "read_file", {}))


def test_resume_blocks_uncertain_side_effect(tmp_path):
    run_id = "34c35c18-58e2-4a0d-ab66-a557d8ed5e7d"

    class CrashSandbox:
        def execute(self, call):
            raise RuntimeError("simulated worker crash after tool intent")

    with pytest.raises(RuntimeError, match="simulated worker crash"):
        M2Runner(tmp_path, sandbox_factory=lambda workspace: CrashSandbox()).run(
            "calculator", run_id=run_id
        )
    safe_sandbox = FakeSandbox()
    resumed = M2Runner(tmp_path, sandbox_factory=lambda workspace: safe_sandbox).resume(run_id)
    assert resumed["status"] == "BLOCKED"
    assert "outcome unknown" in resumed["blocked_reason"]
    assert safe_sandbox.calls == []
