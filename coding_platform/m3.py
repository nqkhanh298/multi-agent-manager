"""M3 DAG batches, isolated Git worktrees, sequential merges and integration QA."""

import json
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .contracts import ToolCall
from .plan import Plan, TaskSpec
from .sandbox import DockerSandbox, SandboxCancelled

BACKEND = """def create_task(title: str) -> dict:
    title = title.strip()
    if not title:
        raise ValueError("title is required")
    return {"id": 1, "title": title, "done": False}
"""
BACKEND_TEST = """import pytest
from backend import create_task


def test_create_task():
    assert create_task("  Buy milk  ") == {"id": 1, "title": "Buy milk", "done": False}


def test_empty_title():
    with pytest.raises(ValueError):
        create_task(" ")
"""
FRONTEND_APP = """import React, { useState } from 'react';

export default function App() {
  const [tasks, setTasks] = useState([]);
  const [title, setTitle] = useState('');
  function addTask(event) {
    event.preventDefault();
    const value = title.trim();
    if (!value) return;
    setTasks([...tasks, { id: crypto.randomUUID(), title: value, done: false }]);
    setTitle('');
  }
  function toggleTask(id) {
    setTasks(tasks.map(task => task.id === id ? { ...task, done: !task.done } : task));
  }
  function removeTask(id) {
    setTasks(tasks.filter(task => task.id !== id));
  }
  return <main>
    <h1>Task Manager</h1>
    <form onSubmit={addTask}>
      <input aria-label="Task title" value={title} onChange={event => setTitle(event.target.value)} />
      <button type="submit">Add task</button>
    </form>
    <ul>{tasks.map(task => <li key={task.id}>
      <label><input type="checkbox" checked={task.done}
        onChange={() => toggleTask(task.id)} />{task.title}</label>
      <button onClick={() => removeTask(task.id)}>Remove</button>
    </li>)}</ul>
  </main>;
}
"""
FRONTEND_MAIN = """import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';

createRoot(document.getElementById('root')).render(<React.StrictMode><App /></React.StrictMode>);
"""
FRONTEND_HTML = """<!doctype html><html lang="en"><head><meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Task Manager</title></head><body><div id="root"></div>
<script type="module" src="/main.jsx"></script></body></html>
"""
INTEGRATION_TEST = """from backend import create_task
from pathlib import Path


def test_backend_contract():
    task = create_task("Ship M3")
    assert task["title"] == "Ship M3"
    assert task["done"] is False


def test_react_bundle_built():
    page = Path("dist/index.html")
    assert page.is_file()
    assert "assets/index-" in page.read_text(encoding="utf-8")
"""


class GitError(RuntimeError):
    pass


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=30, check=False
    )
    if check and completed.returncode != 0:
        raise GitError(completed.stderr[-4000:] or completed.stdout[-4000:])
    return completed


class MockM3Coordinator:
    def create_plan(self, request: str) -> Plan:
        if not request.strip():
            raise ValueError("request must not be empty")
        return Plan.model_validate(
            {
                "tasks": [
                    {
                        "id": "T1",
                        "title": "Build task backend",
                        "agent": "backend_dev",
                        "depends_on": [],
                        "acceptance_criteria": ["Backend unit tests pass"],
                    },
                    {
                        "id": "T2",
                        "title": "Build task frontend",
                        "agent": "frontend_dev",
                        "depends_on": [],
                        "acceptance_criteria": ["React build and render smoke pass"],
                    },
                    {
                        "id": "T3",
                        "title": "Run integration QA",
                        "agent": "qa",
                        "depends_on": ["T1", "T2"],
                        "acceptance_criteria": ["Integration tests pass"],
                    },
                ]
            }
        )


class MockM3Developer:
    def calls(self, task: TaskSpec) -> list[ToolCall]:
        if task.agent == "backend_dev":
            return [
                ToolCall(
                    f"{task.id}-backend", "write_file", {"path": "backend.py", "content": BACKEND}
                ),
                ToolCall(
                    f"{task.id}-backend-test",
                    "write_file",
                    {"path": "test_backend.py", "content": BACKEND_TEST},
                ),
            ]
        if task.agent == "frontend_dev":
            source_root = Path(__file__).resolve().parents[1] / "docker" / "frontend"
            return [
                ToolCall(
                    f"{task.id}-package",
                    "write_file",
                    {
                        "path": "package.json",
                        "content": (source_root / "package.json").read_text(encoding="utf-8"),
                    },
                ),
                ToolCall(
                    f"{task.id}-lock",
                    "write_file",
                    {
                        "path": "package-lock.json",
                        "content": (source_root / "package-lock.json").read_text(encoding="utf-8"),
                    },
                ),
                ToolCall(
                    f"{task.id}-app", "write_file", {"path": "App.jsx", "content": FRONTEND_APP}
                ),
                ToolCall(
                    f"{task.id}-main", "write_file", {"path": "main.jsx", "content": FRONTEND_MAIN}
                ),
                ToolCall(
                    f"{task.id}-html",
                    "write_file",
                    {"path": "index.html", "content": FRONTEND_HTML},
                ),
            ]
        raise ValueError(f"unsupported coding role: {task.agent}")

    def test_command(self, task: TaskSpec) -> list[str]:
        if task.agent == "frontend_dev":
            return ["sh", "/opt/m3/build.sh"]
        return ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_backend.py"]


class M3Runner:
    def __init__(
        self,
        root: Path,
        max_parallel: int = 2,
        coordinator=None,
        developer=None,
        sandbox_factory=None,
    ):
        if not 1 <= max_parallel <= 8:
            raise ValueError("max_parallel must be between 1 and 8")
        self.root = root
        self.max_parallel = max_parallel
        self.coordinator = coordinator or MockM3Coordinator()
        self.developer = developer or MockM3Developer()
        self.sandbox_factory = sandbox_factory or self._default_sandbox

    @staticmethod
    def _default_sandbox(workspace: Path, role: str):
        image = (
            "ai-coding-m3-frontend:local"
            if role in {"frontend_dev", "qa_frontend"}
            else "ai-coding-m1:local"
        )
        return DockerSandbox(workspace, image=image)

    def _initialize(self, run_dir: Path) -> Path:
        repo = run_dir / "repo"
        repo.mkdir(parents=True)
        git(repo, "init", "-b", "integration")
        (repo / "test_integration.py").write_text(INTEGRATION_TEST, encoding="utf-8")
        (repo / ".gitignore").write_text(
            "__pycache__/\n.pytest_cache/\n*.pyc\nnode_modules/\ndist/\n", encoding="utf-8"
        )
        git(repo, "add", "-A")
        git(
            repo,
            "-c",
            "user.name=M3 Runner",
            "-c",
            "user.email=runner@localhost",
            "commit",
            "-m",
            "Initial integration test",
        )
        return repo

    def _prepare_worktree(self, repo: Path, run_dir: Path, task: TaskSpec) -> Path:
        worktree = run_dir / "worktrees" / task.id
        worktree.parent.mkdir(parents=True, exist_ok=True)
        git(repo, "worktree", "add", "-b", f"task-{task.id}", str(worktree), "integration")
        return worktree

    def _execute_task(self, task: TaskSpec, worktree: Path) -> dict:
        started = time.monotonic_ns()
        try:
            sandbox = self.sandbox_factory(worktree, task.agent)
            for call in self.developer.calls(task):
                result = sandbox.execute(call)
                if not result.ok:
                    raise RuntimeError(f"{call.name}: {result.stderr}")
            test = sandbox.execute(
                ToolCall(
                    f"{task.id}-unit-test",
                    "run_command",
                    {"argv": self.developer.test_command(task), "timeout_seconds": 60},
                )
            )
            if not test.ok:
                raise RuntimeError(f"unit test failed: {test.stdout}\n{test.stderr}")
            git(worktree, "add", "-A")
            git(
                worktree,
                "-c",
                "user.name=M3 Runner",
                "-c",
                "user.email=runner@localhost",
                "commit",
                "-m",
                f"Complete {task.id}: {task.title}",
            )
            return {
                "task_id": task.id,
                "status": "COMPLETED",
                "workspace": str(worktree),
                "test_stdout": test.stdout,
                "started_ns": started,
                "ended_ns": time.monotonic_ns(),
            }
        except SandboxCancelled as exc:
            return {
                "task_id": task.id,
                "status": "CANCELLED",
                "workspace": str(worktree),
                "reason": str(exc),
                "started_ns": started,
                "ended_ns": time.monotonic_ns(),
            }
        except (RuntimeError, GitError) as exc:
            return {
                "task_id": task.id,
                "status": "FAILED",
                "workspace": str(worktree),
                "reason": str(exc)[:4000],
                "started_ns": started,
                "ended_ns": time.monotonic_ns(),
            }

    def _merge(self, repo: Path, task: TaskSpec) -> dict:
        merge = git(
            repo,
            "-c",
            "user.name=M3 Runner",
            "-c",
            "user.email=runner@localhost",
            "merge",
            "--no-ff",
            "--no-edit",
            f"task-{task.id}",
            check=False,
        )
        if merge.returncode == 0:
            return {
                "task_id": task.id,
                "status": "MERGED",
                "commit": git(repo, "rev-parse", "HEAD").stdout.strip(),
            }
        conflicts = git(repo, "diff", "--name-only", "--diff-filter=U").stdout.splitlines()
        git(repo, "merge", "--abort", check=False)
        return {
            "task_id": task.id,
            "status": "CONFLICT",
            "files": conflicts,
            "reason": merge.stderr[-4000:] or merge.stdout[-4000:],
        }

    def run(self, request: str, run_id=None, control=None, on_event=None) -> dict:
        run_id = run_id or str(uuid.uuid4())
        run_dir = (self.root / "m3-runs" / run_id).resolve()
        report_path = run_dir / "report.json"
        if report_path.exists():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if report["status"] != "PAUSED":
                raise ValueError("only paused M3 runs can resume")
            plan = Plan.model_validate(report["plan"])
            report["status"] = "RUNNING"
        else:
            plan = Plan.model_validate(self.coordinator.create_plan(request))
            run_dir.mkdir(parents=True, exist_ok=False)
            self._initialize(run_dir)
            report = {
                "run_id": run_id,
                "status": "RUNNING",
                "plan": plan.model_dump(),
                "tasks": [],
                "merges": [],
                "parallel_overlap_ms": 0,
                "integration": None,
            }
        if any(task.agent not in {"backend_dev", "frontend_dev", "qa"} for task in plan.tasks):
            raise ValueError("M3 supports backend_dev, frontend_dev and qa")
        repo = run_dir / "repo"
        completed = {item["task_id"] for item in report["merges"] if item["status"] == "MERGED"}
        completed.update(
            item["task_id"]
            for item in report["tasks"]
            if item["status"] == "COMPLETED"
            and any(task.id == item["task_id"] and task.agent == "qa" for task in plan.tasks)
        )
        pending = {task.id: task for task in plan.tasks if task.id not in completed}

        def save() -> None:
            temporary = report_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
            temporary.replace(report_path)

        save()
        while pending and report["status"] == "RUNNING":
            requested = control() if control else None
            if requested in {"PAUSED", "CANCELLED"}:
                report["status"] = requested
                break
            ready = [
                task
                for task in plan.tasks
                if task.id in pending and set(task.depends_on) <= completed
            ]
            if not ready:
                report.update(status="BLOCKED", reason="no ready tasks")
                break
            batch = ready[: self.max_parallel]
            coding = [task for task in batch if task.agent != "qa"]
            qa = [task for task in batch if task.agent == "qa"]
            if coding:
                worktrees = {
                    task.id: self._prepare_worktree(repo, run_dir, task) for task in coding
                }
                with ThreadPoolExecutor(max_workers=len(coding)) as pool:
                    futures = {
                        pool.submit(self._execute_task, task, worktrees[task.id]): task
                        for task in coding
                    }
                    results = [future.result() for future in as_completed(futures)]
                report["tasks"].extend(results)
                if on_event:
                    for item in results:
                        on_event(
                            "task.status", {"task_id": item["task_id"], "status": item["status"]}
                        )
                if len(results) > 1:
                    start = max(item["started_ns"] for item in results)
                    end = min(item["ended_ns"] for item in results)
                    report["parallel_overlap_ms"] = max(
                        report["parallel_overlap_ms"], max(0, (end - start) // 1_000_000)
                    )
                if any(item["status"] != "COMPLETED" for item in results):
                    report.update(
                        status="CANCELLED"
                        if any(item["status"] == "CANCELLED" for item in results)
                        else "BLOCKED",
                        reason="coding task stopped",
                    )
                    break
                for task in coding:
                    merged = self._merge(repo, task)
                    report["merges"].append(merged)
                    if on_event:
                        on_event("task.merge", {"task_id": task.id, "status": merged["status"]})
                    if merged["status"] != "MERGED":
                        report.update(status="BLOCKED", reason="merge conflict")
                        break
                    completed.add(task.id)
                    del pending[task.id]
                save()
            if report["status"] != "RUNNING":
                break
            for task in qa:
                requested = control() if control else None
                if requested in {"PAUSED", "CANCELLED"}:
                    report["status"] = requested
                    break
                try:
                    build = self.sandbox_factory(repo, "qa_frontend").execute(
                        ToolCall(
                            f"{task.id}-frontend-build",
                            "run_command",
                            {"argv": ["sh", "/opt/m3/build.sh"], "timeout_seconds": 60},
                        )
                    )
                except SandboxCancelled:
                    report["status"] = "CANCELLED"
                    break
                if not build.ok:
                    report["integration"] = {
                        "exit_code": build.exit_code,
                        "stdout": build.stdout,
                        "stderr": build.stderr,
                    }
                    report.update(status="BLOCKED", reason="merged frontend build failed")
                    break
                try:
                    result = self.sandbox_factory(repo, "qa").execute(
                        ToolCall(
                            f"{task.id}-integration",
                            "run_command",
                            {
                                "argv": ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                                "timeout_seconds": 60,
                            },
                        )
                    )
                except SandboxCancelled:
                    report["status"] = "CANCELLED"
                    break
                report["integration"] = {
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "frontend_build": build.stdout,
                }
                report["tasks"].append(
                    {"task_id": task.id, "status": "COMPLETED" if result.ok else "FAILED"}
                )
                if on_event:
                    on_event(
                        "task.status",
                        {"task_id": task.id, "status": "COMPLETED" if result.ok else "FAILED"},
                    )
                if not result.ok:
                    report.update(status="BLOCKED", reason="integration test failed")
                    break
                completed.add(task.id)
                del pending[task.id]
                save()
        if not pending and report["status"] == "RUNNING":
            report["status"] = "COMPLETED"
        save()
        return report
