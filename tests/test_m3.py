import time
from pathlib import Path

from coding_platform.contracts import ToolCall, ToolResult
from coding_platform.m3 import M3Runner
from coding_platform.plan import Plan


class FakeSandbox:
    def __init__(self, workspace: Path, fail_unit=False):
        self.workspace = workspace
        self.fail_unit = fail_unit

    def execute(self, call: ToolCall) -> ToolResult:
        time.sleep(0.04)
        if call.name == "write_file":
            (self.workspace / call.arguments["path"]).write_text(
                call.arguments["content"], encoding="utf-8"
            )
            return ToolResult(call.id, True, 0, changed_files=[call.arguments["path"]])
        failed = self.fail_unit and call.id == "T1-unit-test"
        return ToolResult(call.id, not failed, int(failed), stdout="failed" if failed else "passed")


def test_parallel_worktrees_merge_and_qa(tmp_path):
    report = M3Runner(
        tmp_path, max_parallel=2, sandbox_factory=lambda workspace, role: FakeSandbox(workspace)
    ).run("task app")
    assert report["status"] == "COMPLETED"
    assert report["parallel_overlap_ms"] > 0
    assert [item["status"] for item in report["merges"]] == ["MERGED", "MERGED"]
    workspaces = [item["workspace"] for item in report["tasks"] if "workspace" in item]
    assert len(set(workspaces)) == 2
    repo = tmp_path / "m3-runs" / report["run_id"] / "repo"
    assert (repo / "backend.py").exists() and (repo / "App.jsx").exists()
    assert report["integration"]["exit_code"] == 0


def test_parallel_limit_one_runs_independent_tasks_sequentially(tmp_path):
    report = M3Runner(
        tmp_path, max_parallel=1, sandbox_factory=lambda workspace, role: FakeSandbox(workspace)
    ).run("task app")
    assert report["status"] == "COMPLETED"
    assert report["parallel_overlap_ms"] == 0
    assert [item["task_id"] for item in report["merges"]] == ["T1", "T2"]


def test_pause_then_resume_keeps_merged_progress(tmp_path):
    runner = M3Runner(
        tmp_path, max_parallel=1, sandbox_factory=lambda workspace, role: FakeSandbox(workspace)
    )
    checks = iter([None, "PAUSED"])
    paused = runner.run("task app", run_id="paused-run", control=lambda: next(checks))
    assert paused["status"] == "PAUSED"
    assert [item["task_id"] for item in paused["merges"]] == ["T1"]
    resumed = runner.run("task app", run_id="paused-run")
    assert resumed["status"] == "COMPLETED"
    assert [item["task_id"] for item in resumed["merges"]] == ["T1", "T2"]


def test_dependency_waits_for_merge(tmp_path):
    class DependentCoordinator:
        def create_plan(self, request):
            return Plan.model_validate(
                {
                    "tasks": [
                        {
                            "id": "T1",
                            "title": "Build backend",
                            "agent": "backend_dev",
                            "depends_on": [],
                            "acceptance_criteria": ["done"],
                        },
                        {
                            "id": "T2",
                            "title": "Build frontend",
                            "agent": "frontend_dev",
                            "depends_on": ["T1"],
                            "acceptance_criteria": ["done"],
                        },
                        {
                            "id": "T3",
                            "title": "Integration QA",
                            "agent": "qa",
                            "depends_on": ["T2"],
                            "acceptance_criteria": ["done"],
                        },
                    ]
                }
            )

    report = M3Runner(
        tmp_path,
        max_parallel=2,
        coordinator=DependentCoordinator(),
        sandbox_factory=lambda workspace, role: FakeSandbox(workspace),
    ).run("app")
    assert report["status"] == "COMPLETED"
    assert report["parallel_overlap_ms"] == 0


def test_merge_conflict_blocks_without_qa(tmp_path):
    class ConflictingDeveloper:
        def calls(self, task):
            return [
                ToolCall(
                    task.id,
                    "write_file",
                    {"path": "shared.txt", "content": f"content from {task.id}"},
                )
            ]

        def test_command(self, task):
            return ["python", "-m", "pytest", "-q"]

    report = M3Runner(
        tmp_path,
        developer=ConflictingDeveloper(),
        sandbox_factory=lambda workspace, role: FakeSandbox(workspace),
    ).run("app")
    assert report["status"] == "BLOCKED"
    assert report["reason"] == "merge conflict"
    assert report["merges"][1]["status"] == "CONFLICT"
    assert report["merges"][1]["files"] == ["shared.txt"]
    assert report["integration"] is None


def test_failed_branch_is_not_merged(tmp_path):
    report = M3Runner(
        tmp_path, sandbox_factory=lambda workspace, role: FakeSandbox(workspace, fail_unit=True)
    ).run("app")
    assert report["status"] == "BLOCKED"
    assert report["merges"] == []
