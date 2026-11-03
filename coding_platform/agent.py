import json
import time
from pathlib import Path
from typing import List

from .contracts import ToolResult
from .provider import ModelProvider
from .sandbox import DockerSandbox


class AgentError(RuntimeError):
    pass


class SingleAgent:
    def __init__(
        self, provider: ModelProvider, sandbox: DockerSandbox, audit_path: Path, max_steps: int = 20
    ):
        self.provider = provider
        self.sandbox = sandbox
        self.audit_path = audit_path
        self.max_steps = max_steps
        self._verified_commands = set()

    def run(self, request: str) -> List[ToolResult]:
        history: List[ToolResult] = []
        seen = set()
        self._verified_commands.clear()
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(self.max_steps):
            reply = self.provider.next(request, history)
            if reply.final_answer is not None:
                if (
                    not history
                    or not history[-1].ok
                    or not any(item.tool_call_id in self._verified_commands for item in history)
                ):
                    raise AgentError(reply.final_answer)
                self._audit({"event": "agent.finished", "answer": reply.final_answer})
                return history
            if len(reply.tool_calls) != 1:
                raise AgentError("provider must return exactly one tool call per step")
            call = reply.tool_calls[0]
            if call.id in seen:
                raise AgentError("duplicate tool call ID")
            seen.add(call.id)
            self._audit({"event": "tool.started", "id": call.id, "name": call.name})
            result = self.sandbox.execute(call)
            history.append(result)
            if call.name == "run_command" and result.ok:
                self._verified_commands.add(call.id)
            self._audit(
                {
                    "event": "tool.finished",
                    "id": call.id,
                    "ok": result.ok,
                    "exit_code": result.exit_code,
                    "duration_ms": result.duration_ms,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
        raise AgentError("step budget exceeded")

    def _audit(self, event: dict) -> None:
        event["timestamp_unix_ms"] = int(time.time() * 1000)
        with self.audit_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
