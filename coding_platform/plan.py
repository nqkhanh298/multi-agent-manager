"""Validated Coordinator output for the M2 task DAG."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^T[1-9][0-9]{0,2}$")
    title: str = Field(min_length=3, max_length=120)
    agent: Literal["architect", "backend_dev", "frontend_dev", "qa"]
    depends_on: list[str] = Field(default_factory=list, max_length=20)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=10)


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tasks: list[TaskSpec] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_dag(self) -> "Plan":
        by_id = {task.id: task for task in self.tasks}
        if len(by_id) != len(self.tasks):
            raise ValueError("duplicate task ID")
        for task in self.tasks:
            if len(set(task.depends_on)) != len(task.depends_on):
                raise ValueError("duplicate dependency")
            if any(dep not in by_id for dep in task.depends_on):
                raise ValueError("unknown dependency")
            if task.id in task.depends_on:
                raise ValueError("self dependency")

        visiting: set[str] = set()
        depth_cache: dict[str, int] = {}

        def depth(task_id: str) -> int:
            if task_id in visiting:
                raise ValueError("task DAG contains cycle")
            if task_id in depth_cache:
                return depth_cache[task_id]
            visiting.add(task_id)
            result = 1 + max((depth(dep) for dep in by_id[task_id].depends_on), default=0)
            visiting.remove(task_id)
            if result > 10:
                raise ValueError("task DAG exceeds maximum depth")
            depth_cache[task_id] = result
            return result

        for task_id in by_id:
            depth(task_id)
        return self


class MockCoordinator:
    """Deterministic plan provider for the offline M2 benchmark."""

    def create_plan(self, request: str) -> Plan:
        if not request.strip():
            raise ValueError("request must not be empty")
        return Plan.model_validate(
            {
                "tasks": [
                    {
                        "id": "T1",
                        "title": "Implement calculator and tests",
                        "agent": "backend_dev",
                        "depends_on": [],
                        "acceptance_criteria": ["Calculator code exists"],
                    },
                    {
                        "id": "T2",
                        "title": "Verify calculator with pytest",
                        "agent": "qa",
                        "depends_on": ["T1"],
                        "acceptance_criteria": ["pytest passes"],
                    },
                ]
            }
        )
