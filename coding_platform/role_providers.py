"""Per-user role assignments and direct Claude/Gemini text turns."""

import json
import os
import queue
import re
import threading
from pathlib import Path
from typing import Callable

import httpx

from coding_platform.codex_app_server import CodexStopped

ROLES = (
    "coordinator",
    "researcher",
    "architect",
    "designer",
    "developer",
    "qa",
    "writer",
    "release",
)
PROVIDERS = ("codex", "claude", "gemini")
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")


def default_assignments() -> dict[str, dict[str, str]]:
    return {role: {"provider": "codex", "model": ""} for role in ROLES}


def validate_assignments(value: object) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict) or set(value) != set(ROLES):
        raise ValueError("provide exactly one assignment for every role")
    result = {}
    for role in ROLES:
        item = value[role]
        if not isinstance(item, dict) or set(item) != {"provider", "model"}:
            raise ValueError(f"invalid assignment for {role}")
        provider, model = item["provider"], item["model"]
        if provider not in PROVIDERS or not isinstance(model, str):
            raise ValueError(f"invalid provider or model for {role}")
        if provider != "codex" and not MODEL_RE.fullmatch(model):
            raise ValueError(f"select a model for {role}")
        if provider == "codex" and model and not MODEL_RE.fullmatch(model):
            raise ValueError(f"invalid Codex model for {role}")
        result[role] = {"provider": provider, "model": model}
    return result


def read_assignments(account_dir: Path) -> dict[str, dict[str, str]]:
    path = account_dir / "roles.json"
    return (
        validate_assignments(json.loads(path.read_text(encoding="utf-8")))
        if path.is_file()
        else default_assignments()
    )


def _write_private(path: Path, value: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False)
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def write_assignments(account_dir: Path, assignments: object) -> dict[str, dict[str, str]]:
    checked = validate_assignments(assignments)
    _write_private(account_dir / "roles.json", checked)
    return checked


def read_key(account_dir: Path, provider: str) -> str | None:
    if provider not in {"claude", "gemini"}:
        raise ValueError("unsupported key provider")
    path = account_dir / f"{provider}.key"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def write_key(account_dir: Path, provider: str, key: str) -> None:
    if (
        provider not in {"claude", "gemini"}
        or not key
        or len(key) > 512
        or any(c.isspace() for c in key)
    ):
        raise ValueError("invalid provider key")
    _write_private(account_dir / f"{provider}.key", key)


def remove_key(account_dir: Path, provider: str) -> None:
    if provider not in {"claude", "gemini"}:
        raise ValueError("unsupported key provider")
    (account_dir / f"{provider}.key").unlink(missing_ok=True)


def _request(
    provider: str,
    model: str,
    key: str,
    skill: str,
    prompt: str,
    schema: dict | None,
    stop: Callable[[], str | None] | None,
) -> str:
    system = (
        skill
        + "\nFollow the user's task. Return only a JSON object matching the requested schema when one is provided."
    )
    if schema:
        prompt += "\n\nRequired JSON schema:\n" + json.dumps(schema)
    if provider == "claude":
        url = "https://api.anthropic.com/v1/messages"
        headers = {"Authorization": f"Bearer {key}", "anthropic-version": "2026-10-21"}
        payload = {
            "model": model,
            "max_tokens": 16000 if schema else 4096,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        if schema:
            payload["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
    else:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        headers = {"x-goog-api-key": key}
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 16000 if schema else 4096,
                **(
                    {"responseMimeType": "application/json", "responseJsonSchema": schema}
                    if schema
                    else {}
                ),
            },
        }
    result: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)
    client = httpx.Client(timeout=120)

    def send() -> None:
        try:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            if provider == "claude":
                if data.get("stop_reason") == "max_tokens":
                    raise ValueError("Claude response exceeded token limit")
                text = "".join(
                    block.get("text", "")
                    for block in data.get("content", [])
                    if block.get("type") == "text"
                )
            else:
                candidates = data.get("candidates") or []
                if not candidates:
                    raise ValueError("Gemini returned no candidate")
                if candidates[0].get("finishReason") == "MAX_TOKENS":
                    raise ValueError("Gemini response exceeded token limit")
                text = "".join(
                    part.get("text", "")
                    for part in candidates[0].get("content", {}).get("parts", [])
                )
            if not text.strip():
                raise ValueError(f"{provider} returned an empty response")
            result.put((True, text.strip()))
        except Exception as exc:
            result.put((False, exc))

    thread = threading.Thread(target=send, daemon=True)
    thread.start()
    try:
        while True:
            if stop and (requested := stop()) in {"PAUSED", "CANCELLED"}:
                client.close()
                raise CodexStopped(requested)
            try:
                ok, value = result.get(timeout=0.25)
                if not ok:
                    if isinstance(value, httpx.HTTPStatusError):
                        raise RuntimeError(
                            f"{provider} API returned HTTP {value.response.status_code}"
                        ) from value
                    raise RuntimeError(
                        f"{provider} request failed: {type(value).__name__}"
                    ) from value
                return str(value)
            except queue.Empty:
                continue
    finally:
        client.close()


def run_external_role(
    provider: str,
    model: str,
    key: str,
    skill_path: Path,
    prompt: str,
    schema: dict | None = None,
    stop: Callable[[], str | None] | None = None,
    on_activity: Callable[[str, str], None] | None = None,
) -> str:
    if provider not in {"claude", "gemini"} or not MODEL_RE.fullmatch(model):
        raise ValueError("unsupported provider or model")
    if on_activity:
        on_activity("connecting", f"Đang gọi {provider} · {model}")
    answer = _request(
        provider, model, key, skill_path.read_text(encoding="utf-8"), prompt, schema, stop
    )
    if on_activity:
        on_activity("completed", f"{provider} · {model} đã hoàn thành")
    return answer
