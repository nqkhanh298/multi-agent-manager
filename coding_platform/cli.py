import argparse
import json
import os
import uuid
from pathlib import Path

from .agent import SingleAgent
from .provider import MockCalculatorProvider
from .sandbox import DockerSandbox, SandboxUnavailable


def main() -> int:
    parser = argparse.ArgumentParser(description="Sandboxed coding benchmarks")
    parser.add_argument("command", choices=["demo", "m2-demo", "m2-resume", "m3-demo"])
    parser.add_argument("--root", type=Path, default=Path(".local"))
    parser.add_argument("--run-id")
    parser.add_argument("--pause-after", choices=["implement", "qa"])
    parser.add_argument("--max-retries", type=int, default=int(os.getenv("MAX_TASK_RETRIES", "3")))
    parser.add_argument(
        "--max-parallel", type=int, default=int(os.getenv("MAX_PARALLEL_TASKS", "2"))
    )
    parser.add_argument("--provider", choices=["mock", "openai"], default="mock")
    parser.add_argument("--model", default=os.getenv("LLM_MODEL", "CONFIGURE_ME"))
    parser.add_argument("--prompt", default="Build a Python calculator and run pytest")
    args = parser.parse_args()
    if args.command == "m3-demo":
        if args.provider != "mock":
            parser.error("M3 demo currently supports only the mock provider")
        from .m3 import M3Runner

        request = (
            "Build a task management app"
            if args.prompt == parser.get_default("prompt")
            else args.prompt
        )
        report = M3Runner(args.root, max_parallel=args.max_parallel).run(request)
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "COMPLETED" else 1
    if args.command in {"m2-demo", "m2-resume"}:
        from .m2 import M2Runner, concise_result

        if args.provider == "openai":
            from .m2_openai import OpenAICoordinator, OpenAIDeveloper, OpenAIJSONClient

            client = OpenAIJSONClient(args.model)
            runner = M2Runner(
                args.root,
                max_retries=args.max_retries,
                coordinator=OpenAICoordinator(client),
                developer=OpenAIDeveloper(client),
            )
        else:
            runner = M2Runner(args.root, max_retries=args.max_retries)
        if args.command == "m2-resume":
            if not args.run_id:
                parser.error("m2-resume requires --run-id")
            state = runner.resume(args.run_id)
        else:
            state = runner.run(
                args.prompt, interrupt_after=[args.pause_after] if args.pause_after else None
            )
        print(concise_result(state))
        return 0 if state["status"] == "COMPLETED" or args.pause_after else 1
    run_id = str(uuid.uuid4())
    workspace = args.root / "workspaces" / run_id
    workspace.mkdir(parents=True, exist_ok=False)
    try:
        sandbox = DockerSandbox(workspace, os.getenv("SANDBOX_IMAGE", "ai-coding-m1:local"))
        if args.provider == "openai":
            from .openai_provider import OpenAIResponsesProvider

            provider = OpenAIResponsesProvider(args.model)
        else:
            provider = MockCalculatorProvider()
        agent = SingleAgent(provider, sandbox, args.root / "runs" / run_id / "audit.jsonl")
        results = agent.run(args.prompt)
    except SandboxUnavailable as exc:
        parser.exit(2, f"Sandbox unavailable: {exc}\n")
    print(
        json.dumps(
            {
                "run_id": run_id,
                "workspace": str(workspace),
                "results": [result.__dict__ for result in results],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
