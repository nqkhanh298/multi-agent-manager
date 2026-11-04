"""The Codex path writes model output only through the sandbox boundary."""

import json
import subprocess

import pytest

from coding_platform.codex_run import CodexRunRunner, parse_source, parse_target, parse_web_source
from coding_platform.codex_app_server import CodexAppServer, CodexStopped
from coding_platform.contracts import ToolResult
from coding_platform.codex_roles import default_assignments
from coding_platform.references import REFERENCE_REVIEW_SCHEMA, prepare_references, save_references
import base64


def test_parse_source_rejects_unexpected_fields():
    try:
        parse_source(json.dumps({"app_py": "x", "test_app_py": "y", "extra": "z"}))
    except ValueError:
        pass
    else:
        raise AssertionError("unexpected generated file was accepted")


def test_target_selector_requires_a_supported_exact_target():
    assert parse_target('{"target":"web"}') == "web"
    assert parse_target('{"target":"python_cli"}') == "python_cli"
    for invalid in ('{"target":"desktop"}', '{"target":"web","extra":1}', "[]"):
        with pytest.raises(ValueError):
            parse_target(invalid)


def test_auto_target_is_selected_before_role_handoffs(tmp_path, monkeypatch):
    prompts = []

    class FakeCodex:
        def __init__(self, codex_home):
            pass

        def account(self):
            return {"account": {"type": "chatgpt"}}

        def run_role(self, role, skill, prompt, cwd, **kwargs):
            prompts.append((role, prompt))
            if role == "target_selector":
                assert kwargs["output_schema"]["required"] == ["target"]
                return '{"target":"python_cli"}'
            if role == "developer":
                return json.dumps(
                    {"app_py": "print('hello')", "test_app_py": "def test_ok(): assert True"}
                )
            return f"{role} notes"

        def close(self):
            pass

    class FakeSandbox:
        def __init__(self, workspace, image="", cancel_check=None):
            self.workspace = workspace

        def execute(self, call):
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
        tmp_path / "account",
        target="auto",
    ).run("Make a terminal calculator", "auto-run")
    assert report["status"] == "COMPLETED"
    assert report["target"] == "python_cli"
    assert prompts[0][0] == "target_selector"
    assert "Local Python 3.11 command-line" in prompts[1][1]
    assert ("run.target_selected", {"target": "python_cli"}) in events


def test_codex_turn_uses_current_read_only_policy(tmp_path, monkeypatch):
    client = CodexAppServer()
    requests = []
    monkeypatch.setattr(client, "start", lambda: None)

    def fake_call(method, params=None, timeout=15, stop=None):
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


def test_codex_request_stops_while_waiting_for_server(monkeypatch):
    client = CodexAppServer()
    monkeypatch.setattr(client, "_send", lambda message: None)
    with pytest.raises(CodexStopped) as exc:
        client.call("thread/start", {}, timeout=30, stop=lambda: "CANCELLED")
    assert exc.value.status == "CANCELLED"


@pytest.mark.parametrize(
    ("requested", "task_status"), [("PAUSED", "PENDING"), ("CANCELLED", "CANCELLED")]
)
def test_stopping_codex_clears_running_task(tmp_path, monkeypatch, requested, task_status):
    class FakeCodex:
        def __init__(self, codex_home):
            pass

        def account(self):
            return {"account": {"type": "chatgpt"}}

        def run_role(self, *args, **kwargs):
            raise CodexStopped(requested)

        def close(self):
            pass

    monkeypatch.setattr("coding_platform.codex_run.CodexAppServer", FakeCodex)
    events = []
    report = CodexRunRunner(
        tmp_path,
        lambda kind, payload: events.append((kind, payload)),
        lambda: None,
        tmp_path / "codex-account",
    ).run("Build a clock", "stopped-run")
    assert report["status"] == requested
    assert ("task.status", {"task_id": "T1", "status": task_status}) in events
    assert any(kind == "task.activity" for kind, _ in events)


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
        def __init__(self, workspace, image="ai-coding-m1:local", cancel_check=None):
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
    assert (
        len(
            [
                event
                for event in events
                if event[0] == "task.status" and event[1]["status"] == "COMPLETED"
            ]
        )
        == 8
    )


def test_web_source_schema_and_sandbox_target(tmp_path, monkeypatch):
    source = {
        "index_html": "<html><link rel='stylesheet' href='styles.css'><body><button>Play</button><script src='app.js'></script></body></html>",
        "styles_css": "button { color: purple; }",
        "app_js": "globalThis.gameLogic = { win: () => true };",
        "test_js": "import { test } from 'node:test'; test('works', () => {});",
    }
    assert set(parse_web_source(json.dumps(source))) == {
        "index.html",
        "styles.css",
        "app.js",
        "test.js",
    }
    with pytest.raises(ValueError):
        parse_web_source(json.dumps({**source, "extra": "unexpected"}))
    with pytest.raises(ValueError):
        parse_web_source(
            json.dumps({**source, "index_html": "<html><body>Missing assets</body></html>"})
        )

    images = []
    commands = []
    timeouts = []

    class FakeCodex:
        def __init__(self, codex_home):
            pass

        def account(self):
            return {"account": {"type": "chatgpt"}}

        def run_role(self, role, *args, **kwargs):
            return json.dumps(source) if role == "developer" else f"{role} notes"

        def close(self):
            pass

    class FakeSandbox:
        def __init__(self, workspace, image="", cancel_check=None):
            self.workspace = workspace
            images.append(image)

        def execute(self, call):
            if call.name == "write_file":
                (self.workspace / call.arguments["path"]).write_text(
                    call.arguments["content"], encoding="utf-8"
                )
            else:
                commands.append(call.arguments["argv"])
                timeouts.append(call.arguments["timeout_seconds"])
            return ToolResult(call.id, True, 0, stdout="1 pass")

    monkeypatch.setattr("coding_platform.codex_run.CodexAppServer", FakeCodex)
    monkeypatch.setattr("coding_platform.codex_run.DockerSandbox", FakeSandbox)
    report = CodexRunRunner(
        tmp_path, lambda *args: None, lambda: None, tmp_path / "account", target="web"
    ).run("Build a game", "web-run")
    assert report["status"] == "COMPLETED"
    assert images == ["ai-coding-m3-frontend:local"] * 2
    assert commands == [["node", "--test", "test.js"]]
    assert timeouts == [60]
    assert (tmp_path / "m3-runs/web-run/repo/index.html").is_file()


@pytest.mark.parametrize("valid_evidence", [True, False])
def test_role_runner_uses_separate_codex_models_and_reports_them(
    tmp_path, monkeypatch, valid_evidence
):
    run_id = "reference-valid" if valid_evidence else "reference-invalid"
    reference = prepare_references(
        [
            {
                "name": "requirements.md",
                "data_base64": base64.b64encode(b"The application must print 'ok'.").decode(),
            }
        ]
    )[0]
    save_references(tmp_path / "m3-runs" / run_id, [reference])
    assignments = default_assignments()
    assignments["coordinator"] = {"provider": "codex", "model": "gpt-6-astra"}
    assignments["researcher"] = {"provider": "codex", "model": "gpt-6.1-sol"}
    calls = []
    events = []

    class FakeCodex:
        def __init__(self, codex_home):
            pass

        def account(self):
            return {"account": {"type": "chatgpt"}}

        def run_role(self, role, *args, **kwargs):
            calls.append(("codex", role, kwargs.get("model")))
            assert reference["id"] in args[1]
            assert "The application must print 'ok'." in args[1]
            if role == "qa" and kwargs.get("output_schema") == REFERENCE_REVIEW_SCHEMA:
                return json.dumps(
                    {
                        "summary": "Reference is implemented",
                        "reference_checks": [
                            {
                                "id": reference["id"],
                                "quote": "print 'ok'",
                                "file": "app.py",
                                "evidence": "print('ok')" if valid_evidence else "print('wrong')",
                            }
                        ],
                    }
                )
            if role == "developer":
                return json.dumps(
                    {"app_py": "print('ok')", "test_app_py": "def test_ok(): assert True"}
                )
            return f"{role} notes"

        def close(self):
            pass

    class FakeSandbox:
        def __init__(self, workspace, image="", cancel_check=None):
            self.workspace = workspace

        def execute(self, call):
            if call.name == "write_file":
                (self.workspace / call.arguments["path"]).write_text(call.arguments["content"])
            return ToolResult(call.id, True, 0, stdout="1 passed")

    monkeypatch.setattr("coding_platform.codex_run.CodexAppServer", FakeCodex)
    monkeypatch.setattr("coding_platform.codex_run.DockerSandbox", FakeSandbox)
    report = CodexRunRunner(
        tmp_path,
        lambda kind, payload: events.append((kind, payload)),
        lambda: None,
        tmp_path / "codex-account",
        assignments=assignments,
    ).run("Make a calculator", run_id)
    assert report["status"] == ("COMPLETED" if valid_evidence else "BLOCKED")
    assert ("codex", "researcher", "gpt-6.1-sol") in calls
    assert ("codex", "coordinator", "gpt-6-astra") in calls
    if valid_evidence:
        assert report["reference_checks"][0]["file"] == "app.py"
        assert any(kind == "references.verified" for kind, _ in events)
    else:
        assert "source evidence" in report["reason"]
        assert any(kind == "references.review_failed" for kind, _ in events)
    assert any(
        kind == "task.status"
        and payload.get("provider") == "codex"
        and payload.get("model") == "gpt-6.1-sol"
        for kind, payload in events
    )
