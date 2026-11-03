import json
import os
import subprocess
import time
import uuid
from pathlib import Path

from .contracts import ToolCall, ToolResult


class SandboxUnavailable(RuntimeError):
    pass


class SandboxCancelled(SandboxUnavailable):
    pass


class DockerSandbox:
    """Start a restricted Linux container for each tool call."""

    def __init__(self, workspace: Path, image: str = "ai-coding-m1:local", cancel_check=None):
        self.workspace = workspace.resolve()
        self.image = image
        self.cancel_check = cancel_check
        if os.name != "posix":
            raise SandboxUnavailable("Run the agent inside WSL2/Linux, not on Windows")
        if not self.workspace.is_dir():
            raise ValueError("workspace must exist")

    def execute(self, call: ToolCall) -> ToolResult:
        if call.name not in {"write_file", "read_file", "list_files", "run_command"}:
            raise ValueError("tool not allowed")
        if len(json.dumps(call.arguments)) > 131072:
            raise ValueError("tool arguments too large")
        payload = json.dumps(
            {"tool_call_id": call.id, "name": call.name, "arguments": call.arguments}
        )
        argv = [
            "docker",
            "run",
            "--rm",
            "--interactive",
            "--network",
            "none",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "64",
            "--memory",
            "512m",
            "--cpus",
            "1",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=64m",
            "--mount",
            f"type=bind,src={self.workspace},dst=/workspace",
            "--workdir",
            "/workspace",
        ]
        container_name = f"coding-{uuid.uuid4().hex}"
        if self.cancel_check:
            argv.extend(["--name", container_name])
        argv.append(self.image)
        started = time.monotonic()
        try:
            if self.cancel_check:
                if self.cancel_check():
                    raise SandboxCancelled("sandbox cancelled before start")
                process = subprocess.Popen(
                    argv,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                sent = False
                while True:
                    try:
                        stdout, stderr = process.communicate(
                            input=payload if not sent else None, timeout=0.25
                        )
                        completed = subprocess.CompletedProcess(
                            argv, process.returncode, stdout, stderr
                        )
                        break
                    except subprocess.TimeoutExpired:
                        sent = True
                        cancelled = self.cancel_check()
                        if cancelled or time.monotonic() - started > 125:
                            subprocess.run(
                                ["docker", "rm", "-f", container_name],
                                capture_output=True,
                                timeout=10,
                                check=False,
                            )
                            if process.poll() is None:
                                process.kill()
                            process.communicate()
                            if cancelled:
                                raise SandboxCancelled("sandbox cancelled during tool call")
                            raise SandboxUnavailable("sandbox tool call timed out")
            else:
                completed = subprocess.run(
                    argv, input=payload, text=True, capture_output=True, timeout=125, check=False
                )
        except FileNotFoundError as exc:
            raise SandboxUnavailable("Docker CLI is unavailable") from exc
        except subprocess.TimeoutExpired as exc:
            raise SandboxUnavailable("sandbox tool call timed out") from exc
        if completed.returncode != 0:
            raise SandboxUnavailable(
                f"sandbox exited {completed.returncode}: {completed.stderr[:2000]}"
            )
        try:
            data = json.loads(completed.stdout)
            result = ToolResult.from_dict(data)
        except (ValueError, TypeError) as exc:
            raise SandboxUnavailable("invalid sandbox output") from exc
        if result.tool_call_id != call.id:
            raise SandboxUnavailable("sandbox result call ID mismatch")
        return ToolResult(
            **{**result.__dict__, "duration_ms": int((time.monotonic() - started) * 1000)}
        )
