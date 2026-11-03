"""M2 Coordinator -> Developer -> QA -> bounded repair workflow."""

import json
import uuid
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from .contracts import ToolCall, ToolResult
from .journal import ToolJournal, UncertainToolCall
from .plan import MockCoordinator, Plan
from .provider import CALCULATOR, CALCULATOR_TESTS
from .sandbox import DockerSandbox

BROKEN_CALCULATOR = CALCULATOR.replace("return a / b", "return a // b")
M2_TESTS = (
    CALCULATOR_TESTS + "\n\ndef test_fractional_division():\n    assert divide(5, 2) == 2.5\n"
)


class QAReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    exit_code: int
    stdout: str = Field(max_length=16384)
    stderr: str = Field(max_length=16384)
    attempt: int = Field(ge=0)


class M2State(TypedDict, total=False):
    run_id: str
    request: str
    plan: dict
    status: str
    repair_attempts: int
    test_history: list[dict]
    last_test: dict
    blocked_reason: str
    workspace_ref: str


class MockDeveloper:
    def initial_calls(self, request: str) -> list[ToolCall]:
        return [
            ToolCall(
                "implement-calculator",
                "write_file",
                {"path": "calculator.py", "content": BROKEN_CALCULATOR},
            ),
            ToolCall(
                "implement-tests", "write_file", {"path": "test_calculator.py", "content": M2_TESTS}
            ),
        ]

    def repair_call(self, failure: QAReport, attempt: int, source: str) -> ToolCall:
        if failure.passed or "FAILED" not in failure.stdout:
            raise ValueError("QA failure does not contain a test failure to repair")
        return ToolCall(
            f"repair-calculator-{attempt}",
            "write_file",
            {"path": "calculator.py", "content": CALCULATOR},
        )


class M2Runner:
    def __init__(
        self,
        root: Path,
        max_retries: int = 3,
        coordinator=None,
        developer=None,
        sandbox_factory=None,
    ):
        if not 0 <= max_retries <= 10:
            raise ValueError("max_retries must be between 0 and 10")
        self.root = root
        self.max_retries = max_retries
        self.coordinator = coordinator or MockCoordinator()
        self.developer = developer or MockDeveloper()
        self.sandbox_factory = sandbox_factory or DockerSandbox

    def _paths(self, run_id: str):
        uuid.UUID(run_id)
        workspace = self.root / "workspaces" / run_id
        run_dir = self.root / "runs" / run_id
        return workspace, run_dir

    def _graph(self, journal: ToolJournal, saver: SqliteSaver, interrupt_after=None):
        def plan(state: M2State):
            try:
                proposed = self.coordinator.create_plan(state["request"])
                return {"plan": Plan.model_validate(proposed).model_dump(), "status": "PLANNING"}
            except ValueError as exc:
                return {"status": "BLOCKED", "blocked_reason": str(exc)}

        def validate(state: M2State):
            try:
                validated = Plan.model_validate(state["plan"])
                if (
                    len(validated.tasks) != 2
                    or validated.tasks[0].id != "T1"
                    or validated.tasks[0].agent != "backend_dev"
                    or validated.tasks[1].id != "T2"
                    or validated.tasks[1].agent != "qa"
                    or validated.tasks[1].depends_on != ["T1"]
                ):
                    raise ValueError("M2 workflow requires T1 backend_dev -> T2 qa")
            except ValueError as exc:
                return {"status": "BLOCKED", "blocked_reason": str(exc)}
            return {"status": "RUNNING"}

        def implement(state: M2State):
            try:
                for call in self.developer.initial_calls(state["request"]):
                    result = journal.execute(call)
                    if not result.ok:
                        return {"status": "BLOCKED", "blocked_reason": result.stderr}
            except (UncertainToolCall, ValueError) as exc:
                return {"status": "BLOCKED", "blocked_reason": str(exc)}
            return {"status": "RUNNING"}

        def qa(state: M2State):
            attempt = state.get("repair_attempts", 0)
            call = ToolCall(
                f"qa-pytest-{attempt}",
                "run_command",
                {
                    "argv": ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                    "timeout_seconds": 60,
                },
            )
            try:
                result: ToolResult = journal.execute(call)
            except UncertainToolCall as exc:
                return {"status": "BLOCKED", "blocked_reason": str(exc)}
            report = QAReport(
                passed=result.ok and result.exit_code == 0,
                exit_code=result.exit_code,
                stdout=result.stdout,
                stderr=result.stderr,
                attempt=attempt,
            )
            return {
                "last_test": report.model_dump(),
                "test_history": state.get("test_history", []) + [report.model_dump()],
                "status": "VERIFYING",
            }

        def repair(state: M2State):
            failure = QAReport.model_validate(state["last_test"])
            try:
                attempt = state.get("repair_attempts", 0) + 1
                source_result = journal.execute(
                    ToolCall(
                        f"inspect-calculator-{attempt}", "read_file", {"path": "calculator.py"}
                    )
                )
                if not source_result.ok:
                    return {"status": "BLOCKED", "blocked_reason": source_result.stderr}
                call = self.developer.repair_call(failure, attempt, source_result.stdout)
                result = journal.execute(call)
                if not result.ok:
                    return {"status": "BLOCKED", "blocked_reason": result.stderr}
            except (UncertainToolCall, ValueError) as exc:
                return {"status": "BLOCKED", "blocked_reason": str(exc)}
            return {"status": "RUNNING", "repair_attempts": state.get("repair_attempts", 0) + 1}

        def complete(state: M2State):
            return {"status": "COMPLETED"}

        def block(state: M2State):
            return {
                "status": "BLOCKED",
                "blocked_reason": state.get("blocked_reason", "retry budget exceeded"),
            }

        def after_qa(state: M2State):
            if state["status"] == "BLOCKED":
                return "block"
            if state["last_test"]["passed"]:
                return "complete"
            return "repair" if state.get("repair_attempts", 0) < self.max_retries else "block"

        graph = StateGraph(M2State)
        for name, node in [
            ("plan", plan),
            ("validate", validate),
            ("implement", implement),
            ("qa", qa),
            ("repair", repair),
            ("complete", complete),
            ("block", block),
        ]:
            graph.add_node(name, node)
        graph.add_edge(START, "plan")
        graph.add_conditional_edges(
            "plan", lambda state: "block" if state["status"] == "BLOCKED" else "validate"
        )
        graph.add_conditional_edges(
            "validate", lambda state: "block" if state["status"] == "BLOCKED" else "implement"
        )
        graph.add_conditional_edges(
            "implement", lambda state: "block" if state["status"] == "BLOCKED" else "qa"
        )
        graph.add_conditional_edges("qa", after_qa)
        graph.add_conditional_edges(
            "repair", lambda state: "block" if state["status"] == "BLOCKED" else "qa"
        )
        graph.add_edge("complete", END)
        graph.add_edge("block", END)
        return graph.compile(checkpointer=saver, interrupt_after=interrupt_after)

    def run(self, request: str, run_id: str | None = None, interrupt_after=None) -> M2State:
        run_id = run_id or str(uuid.uuid4())
        workspace, run_dir = self._paths(run_id)
        workspace.mkdir(parents=True, exist_ok=False)
        run_dir.mkdir(parents=True, exist_ok=False)
        journal = ToolJournal(run_dir / "tool_calls.sqlite", self.sandbox_factory(workspace))
        with SqliteSaver.from_conn_string(str(run_dir / "checkpoints.sqlite")) as saver:
            graph = self._graph(journal, saver, interrupt_after=interrupt_after)
            state: M2State = {
                "run_id": run_id,
                "request": request,
                "repair_attempts": 0,
                "test_history": [],
                "status": "CREATED",
                "workspace_ref": str(workspace),
            }
            config = {
                "configurable": {"thread_id": run_id},
                "recursion_limit": max(25, 2 * self.max_retries + 12),
            }
            return graph.invoke(state, config, durability="sync")

    def resume(self, run_id: str) -> M2State:
        workspace, run_dir = self._paths(run_id)
        if not workspace.is_dir() or not (run_dir / "checkpoints.sqlite").is_file():
            raise FileNotFoundError("run checkpoint not found")
        journal = ToolJournal(run_dir / "tool_calls.sqlite", self.sandbox_factory(workspace))
        with SqliteSaver.from_conn_string(str(run_dir / "checkpoints.sqlite")) as saver:
            graph = self._graph(journal, saver)
            config = {
                "configurable": {"thread_id": run_id},
                "recursion_limit": max(25, 2 * self.max_retries + 12),
            }
            return graph.invoke(None, config, durability="sync")

    def snapshot(self, run_id: str) -> dict:
        _, run_dir = self._paths(run_id)
        with SqliteSaver.from_conn_string(str(run_dir / "checkpoints.sqlite")) as saver:
            graph = self._graph(None, saver)
            snap = graph.get_state({"configurable": {"thread_id": run_id}})
            return {"values": snap.values, "next": list(snap.next)}


def concise_result(state: M2State) -> str:
    return json.dumps(
        {
            "run_id": state["run_id"],
            "status": state["status"],
            "repair_attempts": state.get("repair_attempts", 0),
            "tests": state.get("test_history", []),
            "blocked_reason": state.get("blocked_reason"),
        },
        indent=2,
    )
