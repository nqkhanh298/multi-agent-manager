"""Provider interface and deterministic offline benchmark provider."""

from abc import ABC, abstractmethod
from typing import List

from .contracts import ModelReply, ToolCall, ToolResult


class ModelProvider(ABC):
    @abstractmethod
    def next(self, request: str, history: List[ToolResult]) -> ModelReply:
        """Return a tool call or final answer based on prior tool results."""


CALCULATOR = '''"""Small calculator with explicit zero-division behavior."""


def add(a, b):
    return a + b


def subtract(a, b):
    return a - b


def multiply(a, b):
    return a * b


def divide(a, b):
    if b == 0:
        raise ZeroDivisionError("cannot divide by zero")
    return a / b
'''

CALCULATOR_TESTS = """import pytest
from calculator import add, subtract, multiply, divide


def test_operations():
    assert add(2, 3) == 5
    assert subtract(2, 3) == -1
    assert multiply(2, 3) == 6
    assert divide(8, 2) == 4


def test_zero_division():
    with pytest.raises(ZeroDivisionError):
        divide(1, 0)
"""


class MockCalculatorProvider(ModelProvider):
    """Fixed tool-use sequence for offline plumbing and sandbox validation."""

    def next(self, request: str, history: List[ToolResult]) -> ModelReply:
        if not request.strip():
            raise ValueError("request must not be empty")
        if history and not history[-1].ok:
            return ModelReply(final_answer="BLOCKED: last tool call failed")
        step = len(history)
        if step == 0:
            return ModelReply(
                tool_calls=[
                    ToolCall(
                        "write-calculator",
                        "write_file",
                        {"path": "calculator.py", "content": CALCULATOR},
                    )
                ]
            )
        if step == 1:
            return ModelReply(
                tool_calls=[
                    ToolCall(
                        "write-tests",
                        "write_file",
                        {"path": "test_calculator.py", "content": CALCULATOR_TESTS},
                    )
                ]
            )
        if step == 2:
            return ModelReply(
                tool_calls=[
                    ToolCall(
                        "run-pytest",
                        "run_command",
                        {"argv": ["python", "-m", "pytest", "-q"], "timeout_seconds": 60},
                    )
                ]
            )
        return ModelReply(final_answer="Calculator created; pytest passed")
