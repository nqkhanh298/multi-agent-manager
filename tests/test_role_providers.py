"""Codex role model settings are exact and private."""

import json
import os

import pytest

from coding_platform import codex_roles as providers
from coding_platform.codex_app_server import CodexAppServer


def test_assignments_and_private_file(tmp_path):
    assignments = providers.default_assignments()
    assignments["researcher"] = {"provider": "codex", "model": "gpt-6.1-sol"}
    providers.write_assignments(tmp_path / "user", assignments)
    assert providers.read_assignments(tmp_path / "user") == assignments
    if os.name == "posix":
        assert (tmp_path / "user" / "roles.json").stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError):
        providers.validate_assignments({**assignments, "unexpected": assignments["qa"]})
    with pytest.raises(ValueError):
        providers.validate_assignments({**assignments, "qa": {"provider": "gemini", "model": ""}})
    legacy = providers.default_assignments()
    legacy["researcher"] = {"provider": "gemini", "model": "old-model"}
    (tmp_path / "user" / "roles.json").write_text(json.dumps(legacy))
    assert providers.read_assignments(tmp_path / "user")["researcher"] == {
        "provider": "codex",
        "model": "",
    }


def test_codex_thread_receives_selected_model(tmp_path, monkeypatch):
    client = CodexAppServer()
    calls = []
    monkeypatch.setattr(client, "start", lambda: None)

    def call(method, params=None, timeout=15, stop=None):
        calls.append((method, params))
        if method == "thread/start":
            return {"thread": {"id": "thread-1", "model": "gpt-6.1-sol"}}
        if method == "turn/start":
            return {"turn": {"id": "turn-1"}}
        raise AssertionError(method)

    monkeypatch.setattr(client, "call", call)
    monkeypatch.setattr(
        client,
        "notification",
        lambda timeout=1.0: {
            "method": "turn/completed",
            "params": {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed"}},
        },
    )
    activities = []
    client.run_role(
        "qa",
        tmp_path / "SKILL.md",
        "Check",
        tmp_path,
        model="gpt-6.1-sol",
        on_activity=lambda phase, detail: activities.append((phase, detail)),
    )
    assert calls[0][1]["model"] == "gpt-6.1-sol"
    assert ("model", "gpt-6.1-sol") in activities
