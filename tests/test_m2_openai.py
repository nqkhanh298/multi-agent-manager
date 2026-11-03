import json

from coding_platform.m2 import QAReport
from coding_platform.m2_openai import (
    OpenAICoordinator,
    OpenAIDeveloper,
    OpenAIJSONClient,
)


class Response:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *_):
        return json.dumps(self.data).encode()


def test_model_plan_and_repair_without_network(monkeypatch):
    request_bodies = []
    outputs = iter(
        [
            {
                "tasks": [
                    {
                        "id": "T1",
                        "title": "Implement calculator",
                        "agent": "backend_dev",
                        "depends_on": [],
                        "acceptance_criteria": ["code exists"],
                    },
                    {
                        "id": "T2",
                        "title": "Verify calculator",
                        "agent": "qa",
                        "depends_on": ["T1"],
                        "acceptance_criteria": ["pytest passes"],
                    },
                ]
            },
            {
                "calculator_py": "def divide(a,b): return a//b",
                "test_calculator_py": "def test_math(): assert True",
            },
            {"content": "def divide(a,b): return a/b"},
        ]
    )

    def fake_urlopen(request, timeout):
        assert timeout == 90
        request_bodies.append(json.loads(request.data))
        return Response({"status": "completed", "output_text": json.dumps(next(outputs))})

    monkeypatch.setattr("coding_platform.m2_openai.urllib.request.urlopen", fake_urlopen)
    client = OpenAIJSONClient("test-model", api_key="test-key")
    plan = OpenAICoordinator(client).create_plan("calculator")
    assert [task.id for task in plan.tasks] == ["T1", "T2"]
    developer = OpenAIDeveloper(client)
    assert [call.arguments["path"] for call in developer.initial_calls("calculator")] == [
        "calculator.py",
        "test_calculator.py",
    ]
    report = QAReport(passed=False, exit_code=1, stdout="FAILED test_math", stderr="", attempt=0)
    repair = developer.repair_call(report, 1, "def divide(a,b): return a//b")
    assert repair.arguments["content"].endswith("a/b")
    assert all(body["text"]["format"]["strict"] for body in request_bodies)
    assert "test-key" not in json.dumps(request_bodies)
