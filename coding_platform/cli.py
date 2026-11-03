import argparse
import json
import os
import uuid
from pathlib import Path

from .agent import SingleAgent
from .provider import MockCalculatorProvider
from .sandbox import DockerSandbox, SandboxUnavailable


def main() -> int:
    parser = argparse.ArgumentParser(description="M1 sandboxed calculator benchmark")
    parser.add_argument("demo", choices=["demo"])
    parser.add_argument("--root", type=Path, default=Path(".local"))
    parser.add_argument("--provider", choices=["mock", "openai"], default="mock")
    parser.add_argument("--model", default=os.getenv("LLM_MODEL", "CONFIGURE_ME"))
    parser.add_argument("--prompt", default="Build a Python calculator and run pytest")
    args = parser.parse_args()
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
