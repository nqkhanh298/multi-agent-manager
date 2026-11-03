"""Run real Docker sandbox checks from Ubuntu WSL2, outside the Windows host."""

import json
import os
import tempfile
from pathlib import Path

from coding_platform.contracts import ToolCall
from coding_platform.sandbox import DockerSandbox


def main() -> None:
    root = Path(".local/workspaces")
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="security-", dir=root) as directory:
        workspace = Path(directory)
        sandbox = DockerSandbox(workspace)
        checks = {}

        write = sandbox.execute(
            ToolCall("write", "write_file", {"path": "hello.txt", "content": "sandbox proof"})
        )
        read = sandbox.execute(ToolCall("read", "read_file", {"path": "hello.txt"}))
        checks["file_round_trip"] = write.ok and read.ok and read.stdout == "sandbox proof"

        traversal = sandbox.execute(ToolCall("traversal", "read_file", {"path": "../outside"}))
        checks["traversal_blocked"] = not traversal.ok

        (workspace / "link").symlink_to("/etc/passwd")
        symlink = sandbox.execute(ToolCall("symlink", "read_file", {"path": "link"}))
        checks["symlink_blocked"] = not symlink.ok

        identity = sandbox.execute(
            ToolCall(
                "identity",
                "run_command",
                {"argv": ["python", "-c", "import os; print(os.getuid())"], "timeout_seconds": 5},
            )
        )
        checks["non_root"] = (
            identity.ok and identity.stdout.strip() == str(os.getuid()) and os.getuid() != 0
        )

        isolation = sandbox.execute(
            ToolCall(
                "isolation",
                "run_command",
                {
                    "argv": [
                        "python",
                        "-c",
                        (
                            "import os; print(int(any(os.path.exists(p) for p in "
                            "('/var/run/docker.sock', '/mnt/c', '/home/khanhnq298'))))"
                        ),
                    ],
                    "timeout_seconds": 5,
                },
            )
        )
        checks["host_paths_absent"] = isolation.ok and isolation.stdout.strip() == "0"

        network = sandbox.execute(
            ToolCall(
                "network",
                "run_command",
                {
                    "argv": [
                        "python",
                        "-c",
                        (
                            "import socket; s=socket.socket(); s.settimeout(1); "
                            "s.connect(('1.1.1.1', 53))"
                        ),
                    ],
                    "timeout_seconds": 5,
                },
            )
        )
        checks["network_blocked"] = not network.ok

        timeout = sandbox.execute(
            ToolCall(
                "timeout",
                "run_command",
                {"argv": ["python", "-c", "import time; time.sleep(3)"], "timeout_seconds": 1},
            )
        )
        checks["command_timeout"] = not timeout.ok and timeout.exit_code == 124

        print(json.dumps(checks, indent=2))
        if not all(checks.values()):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
