from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass(frozen=True)
class ModelReply:
    tool_calls: List[ToolCall] = field(default_factory=list)
    final_answer: Optional[str] = None


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    ok: bool
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    changed_files: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolResult":
        if not isinstance(data, dict):
            raise ValueError("invalid sandbox result")
        if (
            not isinstance(data.get("tool_call_id"), str)
            or not data["tool_call_id"]
            or type(data.get("ok")) is not bool
            or type(data.get("exit_code")) is not int
        ):
            raise ValueError("invalid sandbox result")
        for key in ("stdout", "stderr"):
            if key in data and (not isinstance(data[key], str) or len(data[key]) > 16384):
                raise ValueError("invalid sandbox output")
        if "duration_ms" in data and (
            type(data["duration_ms"]) is not int or data["duration_ms"] < 0
        ):
            raise ValueError("invalid sandbox duration")
        if "changed_files" in data and (
            not isinstance(data["changed_files"], list)
            or len(data["changed_files"]) > 200
            or not all(isinstance(path, str) for path in data["changed_files"])
        ):
            raise ValueError("invalid changed files")
        return cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data})
