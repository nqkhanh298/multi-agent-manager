"""Real Codex role sessions for applications and research reports."""

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

AUTO_START_TASK = CodexTask(
    "T1", "Điều phối và lập kế hoạch", "coordinator", (), ("Plan selected",)
)
TASK_TITLES = {
    "researcher": "Nghiên cứu vấn đề",
    "architect": "Thiết kế kiến trúc",
    "designer": "Thiết kế trải nghiệm",
    "developer": "Phát triển ứng dụng",
    "qa": "Kiểm tra kết quả",
    "writer": "Viết tài liệu",
    "release": "Đóng gói bàn giao",
}
APP_ROLES = ("researcher", "architect", "designer", "developer", "qa", "writer", "release")
REPORT_ROLES = ("researcher", "designer", "writer", "qa", "release")
PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "target": {"type": "string", "enum": ["web", "python_cli", "research_report"]},
        "roles": {"type": "array", "items": {"type": "string", "enum": list(TASK_TITLES)}},
        "summary": {"type": "string"},
    },
    "required": ["target", "roles", "summary"],
    "additionalProperties": False,
}
REPORT_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["PASS", "FAIL"]},
        "summary": {"type": "string"},
        "reference_checks": REFERENCE_REVIEW_SCHEMA["properties"]["reference_checks"],
    },
    "required": ["verdict", "summary", "reference_checks"],
    "additionalProperties": False,
}


def parse_agent_plan(answer: str) -> tuple[str, tuple[CodexTask, ...], str]:
    data = json.loads(answer)
    if not isinstance(data, dict) or set(data) != {"target", "roles", "summary"}:
        raise ValueError("Coordinator returned an invalid plan")
    target, roles, summary = data["target"], data["roles"], data["summary"]
    if (
        not isinstance(target, str)
        or target not in {"web", "python_cli", "research_report"}
        or not isinstance(roles, list)
    ):
        raise ValueError("Coordinator returned an unsupported target or role list")
    allowed = REPORT_ROLES if target == "research_report" else APP_ROLES
    required = (
        {"researcher", "writer", "qa", "release"}
        if target == "research_report"
        else {"developer", "qa", "release"}
    )
    if (
        any(not isinstance(role, str) for role in roles)
        or len(roles) != len(set(roles))
        or any(role not in allowed for role in roles)
        or not required.issubset(roles)
        or not isinstance(summary, str)
        or not summary.strip()
    ):
        raise ValueError("Coordinator selected incomplete or invalid agent roles")
    ordered = [role for role in allowed if role in roles]
    tasks = [AUTO_START_TASK]
    for role in ordered:
        previous = tasks[-1].id
        tasks.append(
            CodexTask(
                f"T{len(tasks) + 1}",
                TASK_TITLES[role],
                role,
                (previous,),
                ("Role output recorded",),
            )
        )
    return target, tuple(tasks), summary.strip()[:2000]


def task_payload(task: CodexTask) -> dict:
    return {
        "id": task.id,
        "title": task.title,
        "agent": task.agent,
        "depends_on": list(task.depends_on),
        "acceptance_criteria": list(task.acceptance_criteria),
    }


def validate_report(markdown: str) -> str:
    content = markdown.strip()
    if len(content) < 200 or len(content) > 100_000 or not content.startswith("#"):
        raise ValueError("Writer did not produce a complete Markdown research report")
    return content + "\n"


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
        selected_tasks: tuple[CodexTask, ...] = CODEX_TASKS
        if self.target == "auto" and report.get("plan"):
            _, selected_tasks, _ = parse_agent_plan(json.dumps(report["plan"]))
        resolved_models: dict[str, str] = {}
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
                    if activity:
                        activity(
                            "source",
                            "Đã nạp tài liệu tham chiếu: "
                            + ", ".join(str(item["name"]) for item in references),
                        )
                elif role == "researcher" and activity:
                    activity(
                        "source", "Nguồn hiện có: yêu cầu người dùng; không có tài liệu đính kèm"
                    )
                if role == "researcher" and activity:
                    activity("source", "Phiên Codex này không bật truy cập web")
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
            if self.target == "auto" and not report.get("plan"):
                task = AUTO_START_TASK
                self.event("run.target_selection", {"status": "RUNNING"})
                plan_skill = (
                    Path(__file__).resolve().parents[1] / ".agents/skills/coordinator/SKILL.md"
                )

                def planning_activity(phase: str, detail: str) -> None:
                    if phase == "model":
                        self.event("task.model", {"task_id": "T1", "model": detail})
                    else:
                        self.event(
                            "task.activity",
                            {
                                "task_id": "T1",
                                "role": "coordinator",
                                "phase": phase,
                                "detail": detail,
                            },
                        )

                self.event(
                    "task.status",
                    {"task_id": "T1", "status": "RUNNING", **self.assignments["coordinator"]},
                )
                selected = call_role(
                    "coordinator",
                    plan_skill,
                    "Analyze the user's request and choose the smallest suitable team from: "
                    "Researcher (investigation), Architect (software architecture), "
                    "Designer (visual/interaction design), Developer (software), "
                    "Writer (documentation), QA (verification), Release (handoff). "
                    "Choose research_report when the user asks for research, analysis, or a written "
                    "report without requesting software. Choose web for visual apps and python_cli "
                    "only for explicit terminal programs. For a report include researcher, writer, "
                    "qa, release; add designer only when visual layout is requested. For software "
                    "include developer, qa, release; add the other roles only when they add value. "
                    "Return only the requested JSON plan. User request:\n" + prompt,
                    schema=PLAN_SCHEMA,
                    activity=planning_activity,
                )
                target, selected_tasks, summary = parse_agent_plan(selected)
                planning_activity("summary", summary)
                report["target"] = target
                report["plan"] = {
                    "target": target,
                    "roles": [task.agent for task in selected_tasks[1:]],
                    "summary": summary,
                }
                save()
                self.event(
                    "run.plan",
                    {
                        "target": target,
                        "summary": summary,
                        "tasks": [task_payload(task) for task in selected_tasks[1:]],
                    },
                )
                self.event("run.target_selected", {"target": target})
                context["coordinator"] = summary
                (repo / "docs").mkdir(exist_ok=True)
                (repo / "docs" / "coordinator.md").write_text(summary, encoding="utf-8")
                planning_activity("output", "Đã ghi kế hoạch vào docs/coordinator.md")
                report["tasks"].append(
                    {
                        "task_id": "T1",
                        "status": "COMPLETED",
                        "provider": "codex",
                        "model": self.assignments["coordinator"]["model"],
                    }
                )
                completed.add("T1")
                self.event("task.status", {"task_id": "T1", "status": "COMPLETED"})
                save()
            selected_target = report["target"]

            for task in selected_tasks:
                if task.id in completed:
                    continue
                requested = self.control()
                if requested in {"PAUSED", "CANCELLED"}:
                    report["status"] = requested
                    break
                assignment = self.assignments[task.agent]
                self.event("task.status", {"task_id": task.id, "status": "RUNNING", **assignment})

                def activity(phase: str, detail: str) -> None:
                    if phase == "model":
                        resolved_models[task.id] = detail
                        self.event("task.model", {"task_id": task.id, "model": detail})
                        return
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
                    "A sourced Markdown research report. Do not create an application. "
                    "Separate verified facts, analysis, uncertainties, and recommendations."
                    if selected_target == "research_report"
                    else "Standalone interactive browser application using plain HTML, CSS, and JavaScript. "
                    "The user must be able to play through a visual interface in the Preview tab. "
                    "Use no external packages or network resources."
                    if selected_target == "web"
                    else "Local Python 3.11 command-line application using only the standard library."
                )
                brief = f"Target: {target_brief}\n\nUser request:\n{prompt}\n\n" + "\n\n".join(
                    f"{role.upper()}:\n{text[:8000]}" for role, text in context.items()
                )
                if selected_target == "research_report" and task.agent == "writer":
                    answer = call_role(
                        "writer",
                        skill,
                        brief
                        + "\n\nWrite the complete final research report in Markdown. Use source links "
                        "from Researcher only when provided; never invent sources. Include a "
                        "method, findings, limitations, and conclusion. Make it useful to the user.",
                        activity=activity,
                    )
                    report_text = validate_report(answer)
                    (repo / "REPORT.md").write_text(report_text, encoding="utf-8")
                    activity("output", "Đã tạo REPORT.md từ ghi chú nghiên cứu")
                    context["writer"] = report_text
                elif selected_target == "research_report" and task.agent == "qa":
                    document = (repo / "REPORT.md").read_text(encoding="utf-8")
                    answer = call_role(
                        "qa",
                        skill,
                        brief
                        + "\n\nReview REPORT.md against the user's request and Researcher's notes. "
                        "Identify unsupported claims, missing topics, and citation gaps. "
                        "Return JSON verdict PASS only if the report answers the request. "
                        "For each attached reference, quote its exact text and show an exact "
                        "matching passage from REPORT.md; use an empty list when none attached. "
                        "Do not claim external source checks you did not perform.\n\nREPORT.md:\n"
                        + document,
                        schema=REPORT_REVIEW_SCHEMA,
                        activity=activity,
                    )
                    review = json.loads(answer)
                    if review["verdict"] != "PASS":
                        raise ValueError(
                            "QA did not approve the research report: "
                            + str(review.get("summary", ""))[:500]
                        )
                    report["reference_checks"] = verify_reference_review(
                        answer, references, {"REPORT.md": document}
                    )
                    (repo / "docs").mkdir(exist_ok=True)
                    (repo / "docs" / "qa.md").write_text(
                        str(review["summary"])[:100_000], encoding="utf-8"
                    )
                    context["qa"] = str(review["summary"])
                    report["integration"] = {
                        "exit_code": 0,
                        "stdout": str(review["summary"])[:8000],
                        "stderr": "",
                    }
                    if references:
                        self.event(
                            "references.verified", {"ids": [item["id"] for item in references]}
                        )
                elif selected_target == "research_report" and task.agent == "release":
                    answer = call_role(
                        "release",
                        skill,
                        brief
                        + "\n\nSummarize the report handoff and limitations. Do not discuss source code or Docker tests.",
                        activity=activity,
                    )
                    if not answer.strip():
                        raise ValueError("Release returned an empty report handoff")
                    (repo / "docs").mkdir(exist_ok=True)
                    (repo / "docs" / "release.md").write_text(answer[:100_000], encoding="utf-8")
                    context["release"] = answer
                elif task.agent == "developer":
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
                    activity("output", f"Đã ghi kết quả vào {target.relative_to(repo).as_posix()}")
                report["tasks"].append(
                    {
                        "task_id": task.id,
                        "status": "COMPLETED",
                        "provider": assignment["provider"],
                        "model": resolved_models.get(task.id) or assignment["model"],
                        "test_stdout": (report.get("integration") or {}).get("stdout", "")
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
