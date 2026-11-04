"""Real Codex role sessions for a local Python application vertical slice."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from coding_platform.codex_app_server import CodexAppServer, CodexStopped, CodexUnavailable
from coding_platform.contracts import ToolCall
from coding_platform.sandbox import DockerSandbox


@dataclass(frozen=True)
class CodexTask:
    id: str
    title: str
    agent: str
    depends_on: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]


CODEX_TASKS = (
    CodexTask("T1", "Phân tích yêu cầu", "coordinator", (), ("Scope and task plan recorded",)),
    CodexTask("T2", "Nghiên cứu yêu cầu", "researcher", ("T1",), ("Requirements recorded",)),
    CodexTask("T3", "Thiết kế kiến trúc", "architect", ("T2",), ("Architecture recorded",)),
    CodexTask("T4", "Thiết kế trải nghiệm", "designer", ("T3",), ("Interaction design recorded",)),
    CodexTask("T5", "Phát triển ứng dụng", "developer", ("T4",), ("Source and tests created",)),
    CodexTask("T6", "Kiểm thử", "qa", ("T5",), ("Tests pass in Docker",)),
    CodexTask("T7", "Viết hướng dẫn", "writer", ("T6",), ("README written",)),
    CodexTask("T8", "Đóng gói bàn giao", "release", ("T7",), ("Source ZIP created",)),
)

DEVELOPER_SCHEMA = {
    "type": "object",
    "properties": {
        "app_py": {"type": "string"},
        "test_app_py": {"type": "string"},
    },
    "required": ["app_py", "test_app_py"],
    "additionalProperties": False,
}


def commit_generated_source(repo: Path) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, timeout=10)

    git("add", "-A")
    git(
        "-c",
        "user.name=Codex Runner",
        "-c",
        "user.email=runner@localhost",
        "commit",
        "-m",
        "Generated application",
    )


def parse_source(answer: str) -> tuple[str, str]:
    data = json.loads(answer)
    if not isinstance(data, dict) or set(data) != {"app_py", "test_app_py"}:
        raise ValueError("Codex developer returned invalid source fields")
    source, tests = data["app_py"], data["test_app_py"]
    if not all(
        isinstance(item, str) and 0 < len(item.encode()) <= 100_000 for item in (source, tests)
    ):
        raise ValueError("Codex developer returned invalid source size")
    return source, tests


class CodexRunRunner:
    def __init__(
        self,
        root: Path,
        event: Callable[[str, dict], None],
        control: Callable[[], str | None],
        codex_home: Path,
    ):
        self.root = root
        self.event = event
        self.control = control
        self.codex_home = codex_home

    def run(self, prompt: str, run_id: str) -> dict:
        run_dir = (self.root / "m3-runs" / run_id).resolve()
        repo = run_dir / "repo"
        repo.mkdir(parents=True, exist_ok=True)
        if not (repo / ".git").exists():
            subprocess.run(
                ["git", "-C", str(repo), "init", "-b", "main"],
                check=True,
                capture_output=True,
                timeout=10,
            )
            (repo / ".gitignore").write_text(
                "__pycache__/\n.pytest_cache/\n*.pyc\n", encoding="utf-8"
            )
            subprocess.run(
                ["git", "-C", str(repo), "add", ".gitignore"],
                check=True,
                capture_output=True,
                timeout=10,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=Codex Runner",
                    "-c",
                    "user.email=runner@localhost",
                    "commit",
                    "-m",
                    "Initial workspace",
                ],
                check=True,
                capture_output=True,
                timeout=10,
            )
        agent_context = run_dir / "agent-context"
        agent_context.mkdir(exist_ok=True)
        report_path = run_dir / "report.json"
        if report_path.exists():
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if report.get("status") != "PAUSED":
                raise ValueError("only paused Codex runs can resume")
            report["status"] = "RUNNING"
        else:
            report = {
                "run_id": run_id,
                "engine": "codex",
                "status": "RUNNING",
                "tasks": [],
                "integration": None,
            }
        completed = {item["task_id"] for item in report["tasks"] if item["status"] == "COMPLETED"}
        context: dict[str, str] = {}
        for role in (
            "coordinator",
            "researcher",
            "architect",
            "designer",
            "qa",
            "writer",
            "release",
        ):
            file = repo / "docs" / f"{role}.md"
            if file.is_file():
                context[role] = file.read_text(encoding="utf-8")

        def save() -> None:
            temporary = report_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(report_path)

        save()
        client = CodexAppServer(self.codex_home)
        try:
            account = client.account().get("account")
            if not account or account.get("type") != "chatgpt":
                raise CodexUnavailable("ChatGPT account is not connected in this WSL environment")
            for task in CODEX_TASKS:
                if task.id in completed:
                    continue
                requested = self.control()
                if requested in {"PAUSED", "CANCELLED"}:
                    report["status"] = requested
                    break
                self.event("task.status", {"task_id": task.id, "status": "RUNNING"})
                skill = (
                    Path(__file__).resolve().parents[1]
                    / ".agents"
                    / "skills"
                    / task.agent
                    / "SKILL.md"
                )
                if not skill.is_file():
                    raise FileNotFoundError(f"missing {task.agent} skill")
                brief = f"User request:\n{prompt}\n\n" + "\n\n".join(
                    f"{role.upper()}:\n{text[:8000]}" for role, text in context.items()
                )
                if task.agent == "developer":
                    answer = client.run_role(
                        task.agent,
                        skill,
                        brief
                        + "\n\nReturn only JSON matching the requested schema for a Python 3.11 CLI app and pytest tests. Use standard library only.",
                        agent_context,
                        output_schema=DEVELOPER_SCHEMA,
                        stop=self.control,
                    )
                    source, tests = parse_source(answer)
                    sandbox = DockerSandbox(repo)
                    for filename, content in (("app.py", source), ("test_app.py", tests)):
                        result = sandbox.execute(
                            ToolCall(
                                f"{task.id}-{filename}",
                                "write_file",
                                {"path": filename, "content": content},
                            )
                        )
                        if not result.ok:
                            raise RuntimeError(f"could not write {filename}: {result.stderr[:500]}")
                    context[task.agent] = "Created app.py and test_app.py"
                elif task.agent == "qa":
                    sandbox = DockerSandbox(repo)
                    test = sandbox.execute(
                        ToolCall(
                            f"{task.id}-pytest",
                            "run_command",
                            {
                                "argv": ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                                "timeout_seconds": 90,
                            },
                        )
                    )
                    report["integration"] = {
                        "exit_code": test.exit_code,
                        "stdout": test.stdout[:8000],
                        "stderr": test.stderr[:8000],
                    }
                    answer = client.run_role(
                        task.agent,
                        skill,
                        brief
                        + f"\n\nDocker pytest exit code: {test.exit_code}\nstdout:\n{test.stdout[:5000]}\nstderr:\n{test.stderr[:2000]}\nAssess the result; never claim a pass if exit code is nonzero.",
                        agent_context,
                        stop=self.control,
                    )
                    context[task.agent] = answer
                    if not test.ok:
                        raise RuntimeError("generated app failed Docker pytest; see test report")
                else:
                    answer = client.run_role(
                        task.agent, skill, brief, agent_context, stop=self.control
                    )
                    if not answer:
                        raise RuntimeError(f"Codex {task.agent} returned an empty result")
                    context[task.agent] = answer
                    target = repo / (
                        "README.md" if task.agent == "writer" else f"docs/{task.agent}.md"
                    )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(answer[:100_000], encoding="utf-8")
                report["tasks"].append(
                    {
                        "task_id": task.id,
                        "status": "COMPLETED",
                        "test_stdout": report["integration"]["stdout"]
                        if task.agent == "qa"
                        else "",
                    }
                )
                self.event("task.status", {"task_id": task.id, "status": "COMPLETED"})
                completed.add(task.id)
                save()
            if report["status"] == "RUNNING":
                commit_generated_source(repo)
                report["status"] = "COMPLETED"
        except CodexStopped as exc:
            report["status"] = exc.status
        except (
            CodexUnavailable,
            RuntimeError,
            ValueError,
            FileNotFoundError,
            json.JSONDecodeError,
        ) as exc:
            report.update(status="BLOCKED", reason=str(exc)[:1000])
            if "task" in locals():
                self.event("task.status", {"task_id": task.id, "status": "FAILED"})
                report["tasks"].append(
                    {"task_id": task.id, "status": "FAILED", "reason": str(exc)[:1000]}
                )
        finally:
            client.close()
            save()
        return report
