import importlib.util
from pathlib import Path

import pytest

from coding_platform.sandbox import DockerSandbox, SandboxUnavailable


SPEC = importlib.util.spec_from_file_location(
    "sandbox_entrypoint", Path(__file__).parents[1] / "docker" / "sandbox_entrypoint.py"
)
entrypoint = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(entrypoint)


@pytest.mark.parametrize(
    "path", ["../secret", "/etc/passwd", "x/../secret", "x//y", "x\\y", "", ".", "x/./y"]
)
def test_path_rejection(path):
    with pytest.raises(ValueError):
        entrypoint.path_parts(path)


def test_valid_path():
    assert entrypoint.path_parts("src/main.py") == ["src", "main.py"]


def test_windows_host_refuses_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr("coding_platform.sandbox.os.name", "nt")
    with pytest.raises(SandboxUnavailable, match="WSL2"):
        DockerSandbox(tmp_path)
