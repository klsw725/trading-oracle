from __future__ import annotations

import sys

from . import BOOTSTRAP_OBSERVER
from .boundaries import observe_boundaries
from .canonical import JsonValue
from .cli_contract import (CliEnvironment, CliRequest, Command, parser, run_cli_main)
from .config import load_config
from .data_health import health_report
from .errors import FailureCode, V16Failure
from .identity import build_identity
from .health_reporting import health_value
from .input_manifest import load_manifest
from .models import HealthRequest, IdentityRequest, MarketScope
from .paths import confined_file, project_root


def _config_check(request: CliRequest) -> JsonValue:
    root = project_root()
    if request.config is None:
        raise V16Failure(FailureCode.CLI_USAGE_ERROR, "config path required")
    path = confined_file(root, request.config, (".yaml", ".yml"))
    config = load_config(path)
    verified = load_manifest(root, root / "docs/specs/v16/fixtures/input-manifest.json")
    identity = build_identity(IdentityRequest(root=root, config=config,
        manifest_hash=verified.manifest_hash, scope=MarketScope.ALL))
    return {"account_selector": identity.account_selector, "arm_selector": identity.arm_selector,
        "config_hash": identity.config_hash, "config_path": path.relative_to(root).as_posix(),
        "namespaces": list(identity.namespaces), "policy_version": identity.policy_version,
        "runtime_identity": identity.runtime_identity,
        "schema_version": "v16.config-check.1", "status": "PASS"}


def _data_health(request: CliRequest) -> JsonValue:
    root = project_root()
    if request.manifest is None or request.as_of is None or request.scope is None:
        raise V16Failure(FailureCode.CLI_USAGE_ERROR, "health options required")
    verified = load_manifest(root, confined_file(root, request.manifest, (".json",)))
    config = load_config(root / "docs/specs/v16/fixtures/runtime-config.yaml")
    return health_value(health_report(HealthRequest(root=root, verified_manifest=verified,
        config=config, as_of=request.as_of, scope=request.scope)))


def dispatch(request: CliRequest) -> JsonValue:
    if request.command is Command.CONFIG_CHECK:
        return _config_check(request)
    if request.command is Command.DATA_HEALTH:
        return _data_health(request)
    root = project_root()
    network_attempts = BOOTSTRAP_OBSERVER.network_attempts if BOOTSTRAP_OBSERVER else 0
    later_imports = BOOTSTRAP_OBSERVER.later_imports if BOOTSTRAP_OBSERVER else 0
    observer = observe_boundaries(root, network_attempts, later_imports)
    if BOOTSTRAP_OBSERVER is not None:
        BOOTSTRAP_OBSERVER.disable()
    try:
        from .acceptance import prd_acceptance, run_acceptance
        if request.command is Command.ACCEPTANCE:
            return run_acceptance(observer)
        prd = {Command.PRD01: 1, Command.PRD02: 2,
               Command.PRD03: 3, Command.PRD04: 4}[request.command]
        return prd_acceptance(prd, observer)
    finally:
        observer.disable()
        if BOOTSTRAP_OBSERVER is not None:
            BOOTSTRAP_OBSERVER.disable()


def main(argv: tuple[str, ...] | None = None,
         environment: CliEnvironment | None = None) -> int:
    arguments = tuple(sys.argv[1:]) if argv is None else argv
    selected = environment or CliEnvironment(sys.stdout, sys.stderr, dispatch)
    if arguments in (("--help",), ("-h",)):
        _ = selected.stdout.write(parser().format_help())
        return 0
    return run_cli_main(arguments, selected)


if __name__ == "__main__":
    raise SystemExit(main())
