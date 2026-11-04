"""Real Codex role sessions for local CLI and browser applications."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from coding_platform.codex_app_server import CodexAppServer, CodexStopped, CodexUnavailable
from coding_platform.contracts import ToolCall
from coding_platform.sandbox import DockerSandbox, SandboxCancelled
from coding_platform.codex_roles import default_assignments, validate_assignments
from coding_platform.references import (
    REFERENCE_REVIEW_SCHEMA,
    load_references,
    reference_brief,
    verify_reference_review,
)


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

WEB_DEVELOPER_SCHEMA = {
    "type": "object",
    "properties": {
        key: {"type": "string"} for key in ("index_html", "styles_css", "app_js", "test_js")
    },
    "required": ["index_html", "styles_css", "app_js", "test_js"],
    "additionalProperties": False,
}

TARGET_SCHEMA = {
    "type": "object",
    "properties": {"target": {"type": "string", "enum": ["web", "python_cli"]}},
    "required": ["target"],
    "additionalProperties": False,
}


def parse_target(answer: str) -> str:
    data = json.loads(answer)
    if not isinstance(data, dict) or set(data) != {"target"}:
        raise ValueError("Codex target selector returned invalid fields")
    if data["target"] not in {"web", "python_cli"}:
        raise ValueError("Codex target selector returned unsupported target")
    return data["target"]


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


def parse_web_source(answer: str) -> dict[str, str]:
    data = json.loads(answer)
    if not isinstance(data, dict) or set(data) != set(WEB_DEVELOPER_SCHEMA["required"]):
        raise ValueError("Codex developer returned invalid web source fields")
    if not all(
        isinstance(value, str) and 0 < len(value.encode()) <= 100_000 for value in data.values()
    ):
        raise ValueError("Codex developer returned invalid web source size")
    html = data["index_html"].lower()
    if not all(part in html for part in ("<body", "styles.css", "app.js")):
        raise ValueError("Codex developer did not connect the web page to its styles and script")
    return {
        "index.html": data["index_html"],
        "styles.css": data["styles_css"],
        "app.js": data["app_js"],
        "test.js": data["test_js"],
    }


class CodexRunRunner:
    def __init__(
        self,
        root: Path,
        event: Callable[[str, dict], None],
        control: Callable[[], str | None],
        codex_home: Path,
        target: str = "python_cli",
        assignments: dict | None = None,
    ):
        self.root = root
        self.event = event
        self.control = control
        self.codex_home = codex_home
        self.assignments = validate_assignments(assignments or default_assignments())
        if target not in {"python_cli", "web", "auto"}:
            raise ValueError("unsupported Codex target")
        self.target = target

    def run(self, prompt: str, run_id: str) -> dict:
        run_dir = (self.root / "m3-runs" / run_id).resolve()
        references = load_references(run_dir)
        references_text = reference_brief(references)
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
            if report.get("requested_target", report.get("target", "python_cli")) != self.target:
                raise ValueError("Codex target changed during resume")
            report["status"] = "RUNNING"
        else:
            report = {
                "run_id": run_id,
                "engine": "codex_auto"
                if self.target == "auto"
                else "codex_web"
                if self.target == "web"
                else "codex",
                "requested_target": self.target,
                "target": None if self.target == "auto" else self.target,
                "status": "RUNNING",
                "tasks": [],
                "integration": None,
            }
        completed = {item["task_id"] for item in report["tasks"] if item["status"] == "COMPLETED"}
        report["references"] = [
            {key: item[key] for key in ("id", "name", "sha256", "chars")} for item in references
        ]
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

            def call_role(
                role: str,
                skill: Path,
                brief: str,
                *,
                schema: dict | None = None,
                activity: Callable[[str, str], None] | None = None,
            ) -> str:
                assignment = self.assignments["coordinator" if role == "target_selector" else role]
                if references:
                    self.event(
                        "references.injected",
                        {
                            "role": role,
                            "ids": [item["id"] for item in references],
                        },
                    )
                return client.run_role(
                    role,
                    skill,
                    brief + references_text,
                    agent_context,
                    output_schema=schema,
                    stop=self.control,
                    on_activity=activity,
                    **({"model": assignment["model"]} if assignment["model"] else {}),
                )

            account = client.account().get("account")
            if not account or account.get("type") != "chatgpt":
                raise CodexUnavailable("ChatGPT account is not connected in this WSL environment")
            if self.target == "auto" and report["target"] is None:
                self.event("run.target_selection", {"status": "RUNNING"})
                selected = call_role(
                    "target_selector",
                    Path(__file__).resolve().parents[1] / ".agents/skills/target_selector/SKILL.md",
                    f"Choose the application preview target for this request:\n{prompt}",
                    schema=TARGET_SCHEMA,
                    activity=lambda phase, detail: self.event(
                        "run.target_activity", {"phase": phase, "detail": detail}
                    ),
                )
                report["target"] = parse_target(selected)
                save()
                self.event("run.target_selected", {"target": report["target"]})
            selected_target = report["target"]

            for task in CODEX_TASKS:
                if task.id in completed:
                    continue
                requested = self.control()
                if requested in {"PAUSED", "CANCELLED"}:
                    report["status"] = requested
                    break
                assignment = self.assignments[task.agent]
                self.event("task.status", {"task_id": task.id, "status": "RUNNING", **assignment})

                def activity(phase: str, detail: str) -> None:
                    self.event(
                        "task.activity",
                        {"task_id": task.id, "role": task.agent, "phase": phase, "detail": detail},
                    )

                activity("preparing", "Đang chuẩn bị yêu cầu và kết quả từ các vai trò trước")
                skill = (
                    Path(__file__).resolve().parents[1]
                    / ".agents"
                    / "skills"
                    / task.agent
                    / "SKILL.md"
                )
                if not skill.is_file():
                    raise FileNotFoundError(f"missing {task.agent} skill")
                target_brief = (
                    "Standalone interactive browser application using plain HTML, CSS, and JavaScript. "
                    "The user must be able to play through a visual interface in the Preview tab. "
                    "Use no external packages or network resources."
                    if selected_target == "web"
                    else "Local Python 3.11 command-line application using only the standard library."
                )
                brief = f"Target: {target_brief}\n\nUser request:\n{prompt}\n\n" + "\n\n".join(
                    f"{role.upper()}:\n{text[:8000]}" for role, text in context.items()
                )
                if task.agent == "developer":
                    web = selected_target == "web"
                    answer = call_role(
                        task.agent,
                        skill,
                        brief
                        + (
                            "\n\nReturn only JSON matching the schema for a complete interactive browser app. index_html must link styles.css and load app.js. Use plain HTML, CSS and browser JavaScript, with no external packages, CDNs or network calls. app.js must expose pure game logic on globalThis.gameLogic and initialize the UI only when document exists. test_js will be saved as test.js and must use Node 22 built-in node:test and assert modules (and node:vm if useful) to test meaningful rules and an edge case. Make the UI polished, responsive and keyboard accessible."
                            if web
                            else "\n\nReturn only JSON matching the requested schema for a Python 3.11 CLI app and pytest tests. Use standard library only."
                        ),
                        schema=WEB_DEVELOPER_SCHEMA if web else DEVELOPER_SCHEMA,
                        activity=activity,
                    )
                    files = (
                        parse_web_source(answer)
                        if web
                        else dict(zip(("app.py", "test_app.py"), parse_source(answer)))
                    )
                    sandbox = DockerSandbox(
                        repo,
                        image="ai-coding-m3-frontend:local" if web else "ai-coding-m1:local",
                        cancel_check=lambda: self.control() in {"PAUSED", "CANCELLED"},
                    )
                    for filename, content in files.items():
                        activity("sandbox", f"Đang ghi {filename} trong Docker sandbox")
                        result = sandbox.execute(
                            ToolCall(
                                f"{task.id}-{filename}",
                                "write_file",
                                {"path": filename, "content": content},
                            )
                        )
                        if not result.ok:
                            raise RuntimeError(f"could not write {filename}: {result.stderr[:500]}")
                    context[task.agent] = "Created " + ", ".join(files)
                elif task.agent == "qa":
                    web = selected_target == "web"
                    sandbox = DockerSandbox(
                        repo,
                        image="ai-coding-m3-frontend:local" if web else "ai-coding-m1:local",
                        cancel_check=lambda: self.control() in {"PAUSED", "CANCELLED"},
                    )
                    activity(
                        "sandbox",
                        "Đang chạy Node tests trong Docker sandbox"
                        if web
                        else "Đang chạy pytest trong Docker sandbox",
                    )
                    test = sandbox.execute(
                        ToolCall(
                            f"{task.id}-pytest",
                            "run_command",
                            {
                                "argv": ["node", "--test", "test.js"]
                                if web
                                else ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                                "timeout_seconds": 60,
                            },
                        )
                    )
                    report["integration"] = {
                        "exit_code": test.exit_code,
                        "stdout": test.stdout[:8000],
                        "stderr": test.stderr[:8000],
                    }
                    answer = call_role(
                        task.agent,
                        skill,
                        brief
                        + f"\n\nDocker {'Node tests' if web else 'pytest'} exit code: {test.exit_code}\nstdout:\n{test.stdout[:5000]}\nstderr:\n{test.stderr[:2000]}\nAssess the result; never claim a pass if exit code is nonzero.",
                        activity=activity,
                    )
                    context[task.agent] = answer
                    if not test.ok:
                        raise RuntimeError("generated app failed Docker tests; see test report")
                    if references:
                        source_names = (
                            ("index.html", "styles.css", "app.js") if web else ("app.py",)
                        )
                        source = {
                            name: (repo / name).read_text(encoding="utf-8")
                            for name in source_names
                            if (repo / name).is_file()
                        }
                        review = call_role(
                            "qa",
                            skill,
                            "Check EVERY attached reference against the generated source. "
                            "Return one check per reference ID. For each, quote exact text from "
                            "the reference and provide an exact substring from the named source "
                            "file that implements it. If you cannot find implementation evidence, "
                            "return an empty evidence string. Do not invent evidence.\n\n"
                            + "\n\n".join(
                                f"FILE {name}:\n{content}" for name, content in source.items()
                            ),
                            schema=REFERENCE_REVIEW_SCHEMA,
                            activity=activity,
                        )
                        report["reference_checks"] = verify_reference_review(
                            review, references, source
                        )
                        self.event(
                            "references.verified", {"ids": [item["id"] for item in references]}
                        )
                else:
                    answer = call_role(
                        task.agent,
                        skill,
                        brief,
                        activity=activity,
                    )
                    if not answer:
                        raise RuntimeError(f"Codex {task.agent} returned an empty result")
                    requested = self.control()
                    if requested in {"PAUSED", "CANCELLED"}:
                        raise CodexStopped(requested)
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
                        "provider": assignment["provider"],
                        "model": assignment["model"],
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
            if "task" in locals() and task.id not in completed:
                status = "PENDING" if exc.status == "PAUSED" else "CANCELLED"
                self.event("task.status", {"task_id": task.id, "status": status})
                if status == "CANCELLED":
                    report["tasks"].append({"task_id": task.id, "status": status})
        except SandboxCancelled:
            requested = self.control() or "CANCELLED"
            report["status"] = requested
            if "task" in locals() and task.id not in completed:
                status = "PENDING" if requested == "PAUSED" else "CANCELLED"
                self.event("task.status", {"task_id": task.id, "status": status})
                if status == "CANCELLED":
                    report["tasks"].append({"task_id": task.id, "status": status})
        except (
            CodexUnavailable,
            RuntimeError,
            ValueError,
            FileNotFoundError,
            json.JSONDecodeError,
        ) as exc:
            report.update(status="BLOCKED", reason=str(exc)[:1000])
            if references and "QA" in str(exc):
                self.event("references.review_failed", {"reason": str(exc)[:500]})
            if "task" in locals():
                self.event("task.status", {"task_id": task.id, "status": "FAILED"})
                report["tasks"].append(
                    {"task_id": task.id, "status": "FAILED", "reason": str(exc)[:1000]}
                )
        finally:
            client.close()
            save()
        return report
