from __future__ import annotations

from dataclasses import dataclass
from io import StringIO
from pathlib import Path

from .boundaries import (BoundaryObserver, FileSnapshot, forbidden_inputs, snapshot,
                         worktree_snapshot)
from .canonical import JsonValue
from .cli_contract import CliEnvironment, CliRequest, Command, run_cli_main
from .errors import FailureCode, V16Failure
from .fixtures import inventory_paths, verify_inventory
from .reporting import EvidenceItem, item


@dataclass(frozen=True, slots=True)
class BoundaryBaseline:
    inventory_hash: str
    portfolio: FileSnapshot
    tracked_hash: str


def capture_baseline(root: Path) -> BoundaryBaseline:
    return BoundaryBaseline(inventory_hash=verify_inventory(root),
        portfolio=snapshot(root / "data/portfolio.json"), tracked_hash=worktree_snapshot(root).digest)


def cli_checks() -> list[EvidenceItem]:
    def pass_dispatch(_request: CliRequest) -> JsonValue:
        return {"status": "PASS"}

    def fail_dispatch(_request: CliRequest) -> JsonValue:
        return {"status": "FAIL"}

    def typed_failure(_request: CliRequest) -> JsonValue:
        raise V16Failure(FailureCode.INVALID, "typed failure")

    def internal_failure(_request: CliRequest) -> JsonValue:
        _ = int("not-an-integer")
        return {"status": "PASS"}

    command_arguments = {
        Command.CONFIG_CHECK: ("config-check", "--config", "fixture.yaml"),
        Command.DATA_HEALTH: ("data-health", "--manifest", "fixture.json", "--as-of",
                              "2026-01-05T21:00:00Z", "--market", "ALL"),
        Command.PRD01: ("prd01-acceptance",),
        Command.PRD02: ("prd02-acceptance",),
        Command.PRD03: ("prd03-acceptance",),
        Command.PRD04: ("prd04-acceptance",),
        Command.ACCEPTANCE: ("acceptance",),
    }
    command_codes: list[int] = []
    for arguments in command_arguments.values():
        command_codes.append(run_cli_main(arguments, CliEnvironment(
            StringIO(), StringIO(), pass_dispatch)))

    success_out, success_err = StringIO(), StringIO()
    success = run_cli_main(("config-check", "--config", "fixture.yaml"),
                           CliEnvironment(success_out, success_err, pass_dispatch))
    usage_out, usage_err = StringIO(), StringIO()
    usage = run_cli_main(("unknown-command",), CliEnvironment(usage_out, usage_err, pass_dispatch))
    internal_out, internal_err = StringIO(), StringIO()
    internal = run_cli_main(("acceptance",),
                             CliEnvironment(internal_out, internal_err, internal_failure))
    leaf_failure = run_cli_main(command_arguments[Command.CONFIG_CHECK], CliEnvironment(
        StringIO(), StringIO(), typed_failure))
    acceptance_failure = run_cli_main(command_arguments[Command.ACCEPTANCE], CliEnvironment(
        StringIO(), StringIO(), typed_failure))
    returned_failure = run_cli_main(command_arguments[Command.PRD01], CliEnvironment(
        StringIO(), StringIO(), fail_dispatch))
    return [item("prd03_cli_success", "0:PASS:",
                  f"{success}:{_field_text(success_out.getvalue(), 'status')}:{success_err.getvalue()}"),
            item("prd03_cli_usage", "2:CLI_USAGE_ERROR:",
                 f"{usage}:{_field_text(usage_out.getvalue(), 'code')}:{usage_err.getvalue()}"),
             item("prd03_cli_internal", "1:INTERNAL_ERROR:INTERNAL_ERROR\n",
                  f"{internal}:{_field_text(internal_out.getvalue(), 'code')}:{internal_err.getvalue()}"),
             item("prd03_all_command_success", "ALL_ZERO",
                  "ALL_ZERO" if all(code == 0 for code in command_codes) else "NONZERO"),
             item("prd03_typed_failure", "LEAF_2|ACCEPTANCE_1",
                  f"LEAF_{leaf_failure}|ACCEPTANCE_{acceptance_failure}"),
             item("prd03_acceptance_failure", "1", str(returned_failure))]


def _field_text(text: str, name: str) -> str:
    marker = f'"{name}":"'
    start = text.find(marker)
    if start < 0:
        return "MISSING"
    value_start = start + len(marker)
    return text[value_start:text.find('"', value_start)]


def boundary_results(root: Path, observer: BoundaryObserver,
                     baseline: BoundaryBaseline) -> tuple[list[EvidenceItem], list[EvidenceItem]]:
    portfolio_after = snapshot(root / "data/portfolio.json")
    inventory_after = verify_inventory(root)
    tracked_after = worktree_snapshot(root).digest
    forbidden = len(forbidden_inputs(root, inventory_paths(root)))
    later = observer.later_imports
    boundaries = [item("fixture_bytes_unchanged", baseline.inventory_hash, inventory_after),
                  item("forbidden_inputs", "0", str(forbidden)),
                  item("network_calls", "0", str(observer.network_attempts)),
                  item("portfolio_bytes", str(baseline.portfolio), str(portfolio_after)),
                  item("tracked_files_unchanged", baseline.tracked_hash, tracked_after),
                  item("v17_plus_imports", "0", str(later))]
    mutations = [item("later_version_import", "0", str(later)),
                 item("network_attempt", "0", str(observer.network_attempts)),
                 item("portfolio_mutation", str(baseline.portfolio), str(portfolio_after))]
    return boundaries, mutations
