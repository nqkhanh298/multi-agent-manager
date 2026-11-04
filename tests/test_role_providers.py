"""Role routing keeps assignments exact and provider keys private."""

import json
import os

import pytest

from coding_platform import role_providers as providers
from coding_platform.codex_app_server import CodexAppServer


def test_assignments_and_private_keys(tmp_path):
    assignments = providers.default_assignments()
    assignments["researcher"] = {"provider": "claude", "model": "claude-sonnet-5-5"}
    providers.write_assignments(tmp_path / "user", assignments)
    providers.write_key(tmp_path / "user", "claude", "private-test-key")
    assert providers.read_assignments(tmp_path / "user") == assignments
    assert providers.read_key(tmp_path / "user", "claude") == "private-test-key"
    if os.name == "posix":
        assert (tmp_path / "user" / "claude.key").stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError):
        providers.validate_assignments({**assignments, "unexpected": assignments["qa"]})
    with pytest.raises(ValueError):
        providers.validate_assignments({**assignments, "qa": {"provider": "gemini", "model": ""}})
    providers.remove_key(tmp_path / "user", "claude")
    assert providers.read_key(tmp_path / "user", "claude") is None


@pytest.mark.parametrize("provider", ["claude", "gemini"])
def test_direct_provider_uses_model_skill_and_no_key_in_output(tmp_path, monkeypatch, provider):
    skill = tmp_path / "SKILL.md"
    skill.write_text("You are a careful researcher.", encoding="utf-8")
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            if provider == "claude":
                return {
                    "content": [{"type": "text", "text": "research done"}],
                    "stop_reason": "end_turn",
                }
            return {
                "candidates": [
                    {"content": {"parts": [{"text": "research done"}]}, "finishReason": "STOP"}
                ]
            }

    class Client:
        def __init__(self, timeout):
            pass

        def post(self, url, headers, json):
            calls.append((url, headers, json))
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(providers.httpx, "Client", Client)
    result = providers.run_external_role(provider, "my-model", "secret", skill, "Research this")
    assert result == "research done"
    url, headers, payload = calls[0]
    assert "my-model" in (url if provider == "gemini" else payload["model"])
    assert "You are a careful researcher." in json.dumps(payload)
    assert "secret" not in json.dumps(payload)
    assert "secret" in json.dumps(headers)


def test_codex_thread_receives_selected_model(tmp_path, monkeypatch):
    client = CodexAppServer()
    calls = []
    monkeypatch.setattr(client, "start", lambda: None)

    def call(method, params=None, timeout=15, stop=None):
        calls.append((method, params))
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}}
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
    client.run_role("qa", tmp_path / "SKILL.md", "Check", tmp_path, model="gpt-6.1-sol")
    assert calls[0][1]["model"] == "gpt-6.1-sol"
