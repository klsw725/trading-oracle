#!/usr/bin/env python3

import argparse
from pathlib import Path
import sys
from typing import Final, final

from pydantic import TypeAdapter, ValidationError

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.causal.prompt_injection_acceptance import verify_fixture
from src.causal.prompt_injection_gate import (
    PromptAssemblyError,
    build_prompt_package,
    rollback_prompt_package,
)
from src.causal.prompt_injection_models import PROMPT_CONFIG_ADAPTER, PROMPT_PACKAGE_ADAPTER
from src.v4.models import (
    ArtifactConflictError,
    JsonValue,
    canonical_json,
    write_immutable_json,
)


_JSON: Final[TypeAdapter[JsonValue]] = TypeAdapter(JsonValue)


@final
class CliArgs:
    command: str | None = None
    fixture: Path = Path("docs/specs/v5/fixtures/prd04-prompt-injection-gate.json")
    source: Path = Path("data/causal_statistical_verification.json")
    config: Path = fixture
    prior: Path | None = None
    output: Path = Path("data/causal_prompt_injection.json")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build strict causal prompt evidence packages")
    commands = parser.add_subparsers(dest="command", required=True)
    fixture = commands.add_parser("verify-fixture")
    _ = fixture.add_argument("--fixture", type=Path, default=CliArgs.fixture)
    build = commands.add_parser("build")
    _ = build.add_argument("--source", type=Path, required=True)
    _ = build.add_argument("--config", type=Path, required=True)
    _ = build.add_argument("--prior", type=Path)
    _ = build.add_argument("--output", type=Path, required=True)
    rollback = commands.add_parser("rollback")
    _ = rollback.add_argument("--prior", type=Path, required=True)
    _ = rollback.add_argument("--config", type=Path, required=True)
    _ = rollback.add_argument("--output", type=Path, required=True)
    return parser


def _load(path: Path) -> JsonValue:
    return _JSON.validate_json(path.read_bytes())


def _emit(value: JsonValue) -> None:
    print(canonical_json(value).decode("utf-8"))


def _write(args: CliArgs, artifact: JsonValue, rolled_back: bool) -> int:
    status = write_immutable_json(args.output, artifact)
    _emit(
        {
            "state": "pass",
            "output": str(args.output),
            "rolled_back": rolled_back,
            "write_status": status.value,
        }
    )
    return 0


def main() -> int:
    args = CliArgs()
    _ = _parser().parse_args(namespace=args)
    try:
        if args.command == "verify-fixture":
            result = verify_fixture(_load(args.fixture))
            _emit(result)
            return 0 if isinstance(result, dict) and result.get("state") == "pass" else 1
        config = PROMPT_CONFIG_ADAPTER.validate_python(_load(args.config))
        protected_paths = {args.config.resolve(), args.source.resolve()}
        if args.prior is not None:
            protected_paths.add(args.prior.resolve())
        if args.output.resolve() in protected_paths:
            _emit({"state": "fail", "reason": "output_must_be_a_new_artifact"})
            return 1
        if args.command == "rollback" and args.prior is not None:
            return _write(args, rollback_prompt_package(_load(args.prior), config).artifact, True)
        if args.command == "build":
            try:
                artifact = build_prompt_package(
                    _load(args.source),
                    config,
                    None
                    if args.prior is None
                    else PROMPT_PACKAGE_ADAPTER.validate_python(
                        _load(args.prior)
                    ).package_hash,
                ).artifact
            except (PromptAssemblyError, ValidationError):
                if args.prior is None:
                    raise
                artifact = rollback_prompt_package(_load(args.prior), config).artifact
                return _write(args, artifact, True)
            return _write(args, artifact, False)
        return 1
    except (
        ArtifactConflictError,
        OSError,
        PromptAssemblyError,
        ValidationError,
        ValueError,
    ) as error:
        _emit({"state": "fail", "error": type(error).__name__, "detail": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
