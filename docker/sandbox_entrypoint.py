"""Runs inside a network-disabled, non-root sandbox container only."""

import json
import os
import subprocess
import sys
import time

ROOT = "/workspace"
MAX_OUTPUT = 16384
MAX_FILE = 131072


def path_parts(path):
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path:
        raise ValueError("invalid relative path")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("invalid path component")
    return parts


def open_parent(parts):
    fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def write_file(path, content):
    parts = path_parts(path)
    if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FILE:
        raise ValueError("file content too large")
    parent = open_parent(parts)
    name = parts[-1]
    temp = ".tmp-" + os.urandom(12).hex()
    try:
        try:
            existing = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            try:
                if not os.path.isfile(f"/proc/self/fd/{existing}"):
                    raise ValueError("target is not a regular file")
            finally:
                os.close(existing)
        fd = os.open(
            temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(content.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, name, src_dir_fd=parent, dst_dir_fd=parent)
        except BaseException:
            os.unlink(temp, dir_fd=parent)
            raise
    finally:
        os.close(parent)
    return {"changed_files": [path]}


def read_file(path):
    parts = path_parts(path)
    parent = open_parent(parts)
    try:
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        with os.fdopen(fd, "rb") as stream:
            content = stream.read(MAX_FILE + 1)
        if len(content) > MAX_FILE:
            raise ValueError("file too large")
        return {"stdout": content.decode("utf-8")}
    finally:
        os.close(parent)


def list_files(path):
    if path in ("", "."):
        fd = os.open(ROOT, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    else:
        parts = path_parts(path)
        parent = open_parent(parts)
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        finally:
            os.close(parent)
    try:
        names = sorted(os.listdir(fd))[:200]
        return {"stdout": "\n".join(names)}
    finally:
        os.close(fd)


def run_command(argv, timeout_seconds):
    if (
        not isinstance(argv, list)
        or not argv
        or len(argv) > 32
        or not all(isinstance(item, str) and 0 < len(item) <= 1024 for item in argv)
    ):
        raise ValueError("invalid argv")
    if not isinstance(timeout_seconds, int) or not 1 <= timeout_seconds <= 60:
        raise ValueError("invalid timeout")
    try:
        completed = subprocess.run(
            argv,
            cwd=ROOT,
            shell=False,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "HOME": "/tmp",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
        )
        return {
            "ok": completed.returncode == 0,
            "exit_code": completed.returncode,
            "stdout": completed.stdout[:MAX_OUTPUT].decode("utf-8", "replace"),
            "stderr": completed.stderr[:MAX_OUTPUT].decode("utf-8", "replace"),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": 124, "stderr": "command timed out"}


def main():
    call = json.load(sys.stdin)
    call_id = call["tool_call_id"]
    name = call["name"]
    args = call["arguments"]
    started = time.monotonic()
    result = {
        "tool_call_id": call_id,
        "ok": True,
        "exit_code": 0,
        "stdout": "",
        "stderr": "",
        "changed_files": [],
    }
    try:
        if name == "write_file":
            result.update(write_file(args["path"], args["content"]))
        elif name == "read_file":
            result.update(read_file(args["path"]))
        elif name == "list_files":
            result.update(list_files(args.get("path", ".")))
        elif name == "run_command":
            result.update(run_command(args["argv"], args["timeout_seconds"]))
        else:
            raise ValueError("tool not allowed")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result.update({"ok": False, "exit_code": 1, "stderr": str(exc)[:MAX_OUTPUT]})
    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
