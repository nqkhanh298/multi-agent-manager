"""Terminal preview forwards user input to generated code with bounded output."""

import importlib.util
import sys
from pathlib import Path


def test_sandbox_command_accepts_terminal_input(tmp_path):
    path = Path(__file__).resolve().parents[1] / "docker" / "sandbox_entrypoint.py"
    spec = importlib.util.spec_from_file_location("sandbox_entrypoint_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = str(tmp_path)
    result = module.run_command([sys.executable, "-c", "print('Name: ' + input())"], 5, "An\n")
    assert result["ok"] is True
    assert result["stdout"] == "Name: An\n"
