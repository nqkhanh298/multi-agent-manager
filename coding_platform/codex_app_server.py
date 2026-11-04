"""Small JSONL client for the local Codex app-server process.

The Codex process owns ChatGPT credentials. This module never reads its auth cache.
"""

import json
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable


class CodexUnavailable(RuntimeError):
    pass


class CodexStopped(RuntimeError):
    def __init__(self, status: str):
        self.status = status
        super().__init__(f"Codex run {status.lower()}")


def codex_binary() -> str:
    configured = os.getenv("CODEX_BIN")
    found = configured or shutil.which("codex")
    if not found:
        local = Path.home() / ".local" / "bin" / "codex"
        found = str(local) if local.is_file() else None
    if not found:
        raise CodexUnavailable("Codex CLI is not installed in the API/worker environment")
    return found


class CodexAppServer:
    def __init__(self, codex_home: Path | None = None) -> None:
        self.codex_home = codex_home
        self.process: subprocess.Popen[str] | None = None
        self._next_id = 0
        self._id_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._pending: dict[int, queue.Queue[dict]] = {}
        self._notifications: queue.Queue[dict] = queue.Queue()

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        environment = os.environ.copy()
        if self.codex_home is not None:
            self.codex_home.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.codex_home.chmod(0o700)
            environment["CODEX_HOME"] = str(self.codex_home)
        self.process = subprocess.Popen(
            [codex_binary(), "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            env=environment,
        )
        threading.Thread(target=self._read_loop, daemon=True).start()
        self.call(
            "initialize",
            {
                "clientInfo": {
                    "name": "multi_agent_manager",
                    "title": "Multi-Agent Manager",
                    "version": "0.7.0",
                }
            },
        )
        self._send({"method": "initialized", "params": {}})

    def _send(self, message: dict) -> None:
        if self.process is None or self.process.poll() is not None or self.process.stdin is None:
            raise CodexUnavailable("Codex app-server is not running")
        with self._write_lock:
            self.process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self.process.stdin.flush()

    def _read_loop(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            request_id = message.get("id")
            if request_id is not None and "method" in message:
                # This connector does not grant extra command, file or network access.
                method = message["method"]
                result = (
                    {"permissions": {}}
                    if method == "item/permissions/requestApproval"
                    else {"decision": "decline"}
                )
                try:
                    self._send({"id": request_id, "result": result})
                except CodexUnavailable:
                    break
            elif request_id is not None:
                pending = self._pending.get(request_id)
                if pending:
                    pending.put(message)
            elif "method" in message:
                self._notifications.put(message)

    def call(self, method: str, params: dict | None = None, timeout: int = 15) -> dict:
        with self._id_lock:
            self._next_id += 1
            request_id = self._next_id
        result_queue: queue.Queue[dict] = queue.Queue(maxsize=1)
        self._pending[request_id] = result_queue
        try:
            self._send({"id": request_id, "method": method, "params": params or {}})
            try:
                message = result_queue.get(timeout=timeout)
            except queue.Empty as exc:
                raise CodexUnavailable(f"Codex did not respond to {method}") from exc
            if "error" in message:
                error = message["error"]
                raise CodexUnavailable(str(error.get("message", "Codex request failed")))
            return message.get("result") or {}
        finally:
            self._pending.pop(request_id, None)

    def notification(self, timeout: float = 1.0) -> dict | None:
        try:
            return self._notifications.get(timeout=timeout)
        except queue.Empty:
            return None

    def account(self) -> dict:
        self.start()
        return self.call("account/read")

    def begin_login(self, method: str = "browser") -> dict:
        self.start()
        if method == "device":
            return self.call("account/login/start", {"type": "chatgptDeviceCode"})
        return self.call("account/login/start", {"type": "chatgpt"})

    def logout(self) -> None:
        self.start()
        self.call("account/logout")

    def run_role(
        self,
        role: str,
        skill: Path,
        prompt: str,
        cwd: Path,
        timeout: int = 300,
        output_schema: dict | None = None,
        stop: Callable[[], str | None] | None = None,
    ) -> str:
        self.start()
        thread = self.call(
            "thread/start",
            {"cwd": str(cwd), "approvalPolicy": "on-request", "sandbox": "read-only"},
            timeout=30,
        )
        thread_id = thread["thread"]["id"]
        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [
                {"type": "text", "text": f"${role}\n{prompt}"},
                {"type": "skill", "name": role, "path": str(skill)},
            ],
            "cwd": str(cwd),
            "approvalPolicy": "on-request",
            "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
        }
        if output_schema is not None:
            params["outputSchema"] = output_schema
        turn = self.call("turn/start", params, timeout=30)
        turn_id = turn["turn"]["id"]
        chunks: list[str] = []
        final_message = ""
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            requested = stop() if stop else None
            if requested in {"PAUSED", "CANCELLED"}:
                self.call("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
                raise CodexStopped(requested)
            event = self.notification(timeout=min(1.0, max(0.01, deadline - time.monotonic())))
            if not event:
                continue
            params = event.get("params") or {}
            if params.get("threadId") != thread_id:
                continue
            if event["method"] == "item/agentMessage/delta":
                chunks.append(params.get("delta", ""))
            elif event["method"] == "item/completed":
                item = params.get("item") or {}
                if item.get("type") == "agentMessage" and item.get("text"):
                    final_message = item["text"]
            elif (
                event["method"] == "turn/completed" and params.get("turn", {}).get("id") == turn_id
            ):
                if params["turn"].get("status") != "completed":
                    raise CodexUnavailable(f"Codex {role} turn {params['turn'].get('status')}")
                return (final_message or "".join(chunks)).strip()
        self.call("turn/interrupt", {"threadId": thread_id, "turnId": turn_id})
        raise CodexUnavailable(f"Codex {role} exceeded {timeout} seconds")

    def close(self) -> None:
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
