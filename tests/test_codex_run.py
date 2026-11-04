"""The Codex path writes model output only through the sandbox boundary."""

import json
import subprocess

from coding_platform.codex_run import CodexRunRunner, parse_source
from coding_platform.codex_app_server import CodexAppServer
from coding_platform.contracts import ToolResult


def test_parse_source_rejects_unexpected_fields():
    try:
        parse_source(json.dumps({"app_py": "x", "test_app_py": "y", "extra": "z"}))
    except ValueError:
        pass
    else:
        raise AssertionError("unexpected generated file was accepted")


def test_codex_turn_uses_current_read_only_policy(tmp_path, monkeypatch):
    client = CodexAppServer()
    requests = []
    monkeypatch.setattr(client, "start", lambda: None)

    def fake_call(method, params=None, timeout=15):
        requests.append((method, params))
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}}
        if method == "turn/start":
            return {"turn": {"id": "turn-1"}}
        raise AssertionError(method)

    monkeypatch.setattr(client, "call", fake_call)
    monkeypatch.setattr(
        client,
        "notification",
        lambda timeout=1.0: {
            "method": "turn/completed",
            "params": {
                "threadId": "thread-1",
                "turn": {"id": "turn-1", "status": "completed"},
            },
        },
    )
    client.run_role("coordinator", tmp_path / "SKILL.md", "Plan", tmp_path)
    turn = next(params for method, params in requests if method == "turn/start")
    assert turn["sandboxPolicy"] == {"type": "readOnly", "networkAccess": False}


def test_codex_roles_generate_files_and_verify_in_sandbox(tmp_path, monkeypatch):
    roles: list[str] = []
    calls: list[str] = []

    class FakeCodex:
        def __init__(self, codex_home):
            assert codex_home == tmp_path / "codex-account"

        def account(self):
            return {"account": {"type": "chatgpt"}}

        def run_role(self, role, skill, prompt, cwd, **kwargs):
            roles.append(role)
            assert skill.name == "SKILL.md"
            assert cwd.name == "agent-context"
            assert "Build a clock" in prompt
            if role == "developer":
                return json.dumps(
                    {
                        "app_py": "def now():\n    return '12:00'\n",
                        "test_app_py": "from app import now\ndef test_now():\n    assert now() == '12:00'\n",
                    }
                )
            return f"{role} output"

        def close(self):
            pass

    class FakeSandbox:
        def __init__(self, workspace):
            self.workspace = workspace

        def execute(self, call):
            calls.append(call.name)
            if call.name == "write_file":
                (self.workspace / call.arguments["path"]).write_text(
                    call.arguments["content"], encoding="utf-8"
                )
            return ToolResult(call.id, True, 0, stdout="1 passed")

    monkeypatch.setattr("coding_platform.codex_run.CodexAppServer", FakeCodex)
    monkeypatch.setattr("coding_platform.codex_run.DockerSandbox", FakeSandbox)
    events = []
    report = CodexRunRunner(
        tmp_path,
        lambda kind, payload: events.append((kind, payload)),
        lambda: None,
        tmp_path / "codex-account",
    ).run("Build a clock", "run-1")
    assert report["status"] == "COMPLETED"
    assert roles == [
        "coordinator",
        "researcher",
        "architect",
        "designer",
        "developer",
        "qa",
        "writer",
        "release",
    ]
    assert calls == ["write_file", "write_file", "run_command"]
    repo = tmp_path / "m3-runs" / "run-1" / "repo"
    assert "def now" in (repo / "app.py").read_text(encoding="utf-8")
    assert (repo / "README.md").is_file()
    first_commit = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--max-parents=0", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    source_diff = subprocess.run(
        ["git", "-C", str(repo), "diff", first_commit, "HEAD", "--", "app.py"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "+def now()" in source_diff
    assert len([event for event in events if event[1]["status"] == "COMPLETED"]) == 8
