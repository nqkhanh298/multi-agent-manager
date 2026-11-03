import json

import pytest

from coding_platform.agent import AgentError, SingleAgent
from coding_platform.contracts import ToolResult
from coding_platform.provider import MockCalculatorProvider


class FakeSandbox:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def execute(self, call):
        self.calls.append(call)
        code = 1 if self.fail and call.name == "run_command" else 0
        return ToolResult(call.id, code == 0, code)


def test_mock_agent_calls_tools_and_audits(tmp_path):
    sandbox = FakeSandbox()
    audit = tmp_path / "audit.jsonl"
    results = SingleAgent(MockCalculatorProvider(), sandbox, audit).run("calculator")
    assert [call.name for call in sandbox.calls] == ["write_file", "write_file", "run_command"]
    assert all(result.ok for result in results)
    events = [json.loads(line) for line in audit.read_text().splitlines()]
    assert [event["event"] for event in events].count("tool.finished") == 3
    assert events[-1]["event"] == "agent.finished"


def test_failing_test_does_not_report_success(tmp_path):
    with pytest.raises(AgentError, match="BLOCKED"):
        SingleAgent(MockCalculatorProvider(), FakeSandbox(fail=True), tmp_path / "audit.jsonl").run(
            "calculator"
        )


def test_step_budget(tmp_path):
    with pytest.raises(AgentError, match="budget"):
        SingleAgent(
            MockCalculatorProvider(), FakeSandbox(), tmp_path / "audit.jsonl", max_steps=2
        ).run("calculator")


@pytest.mark.parametrize(
    "data",
    [
        {"tool_call_id": "x", "ok": "yes", "exit_code": 0},
        {"tool_call_id": "x", "ok": True, "exit_code": False},
        {"tool_call_id": "x", "ok": True, "exit_code": 0, "stdout": 5},
    ],
)
def test_invalid_sandbox_result_is_rejected(data):
    with pytest.raises(ValueError, match="invalid"):
        ToolResult.from_dict(data)
