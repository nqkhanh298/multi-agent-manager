"""Per-user Codex model assignments for the eight specialist roles."""

import json
import os
import re
from pathlib import Path

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
        model = item["model"]
        if item["provider"] != "codex" or not isinstance(model, str):
            raise ValueError(f"only Codex is supported for {role}")
        if model and not MODEL_RE.fullmatch(model):
            raise ValueError(f"invalid Codex model for {role}")
        result[role] = {"provider": "codex", "model": model}
    return result


def read_assignments(account_dir: Path) -> dict[str, dict[str, str]]:
    path = account_dir / "roles.json"
    if not path.is_file():
        return default_assignments()
    saved = json.loads(path.read_text(encoding="utf-8"))
    # Previous releases allowed external providers. Retain Codex choices and
    # reset removed providers to the connected account's default model.
    if isinstance(saved, dict) and set(saved) == set(ROLES):
        saved = {
            role: item
            if isinstance(item, dict) and item.get("provider") == "codex"
            else {"provider": "codex", "model": ""}
            for role, item in saved.items()
        }
    return validate_assignments(saved)


def write_assignments(account_dir: Path, assignments: object) -> dict[str, dict[str, str]]:
    checked = validate_assignments(assignments)
    account_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    account_dir.chmod(0o700)
    path = account_dir / "roles.json"
    temporary = path.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(checked, stream, ensure_ascii=False)
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    return checked
