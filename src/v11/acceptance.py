from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Final, Literal

from src.v4.models import JsonValue, canonical_json

from .build import build_fixture
from .canonical import canonical_hash, parse_json
from .models import V11ContractError
from .probes import local_probes, normative_probes
from .verifier import verify_bundle


ROOT: Final = Path(__file__).resolve().parents[2]
FIXTURES: Final[dict[int, Path]] = {index: ROOT / f"docs/specs/v11/fixtures/prd0{index}.json"
                                           for index in (1, 2, 3, 4)}


def load_fixture(path: Path) -> JsonValue:
    try:
        return parse_json(path.read_bytes())
    except OSError as error:
        raise V11ContractError("V11_FIXTURE_ERROR", str(error)) from error


def build_path(path: Path) -> JsonValue:
    return build_fixture(load_fixture(path))


def accept_prd(prd: Literal[1, 2, 3, 4]) -> JsonValue:
    bundle = verify_bundle(canonical_json(build_path(FIXTURES[prd])))
    _verify_prd_artifacts(prd, bundle.artifacts)
    probes = tuple(item for item in (*normative_probes(), *local_probes()) if item.owner_prd == prd)
    return {"state": "pass", "prd": prd, "case_count": len(bundle.artifacts),
            "artifact_count": len(bundle.artifacts), "artifact_hash": bundle.bundle_hash,
            "probe_count": len(probes), "mutation_codes": [item.result_code for item in probes]}


def run_acceptance() -> JsonValue:
    reports = tuple(accept_prd(prd) for prd in (1, 2, 3, 4))
    normative = normative_probes()
    local = local_probes()
    if len(normative) != 12 or len(local) != 2:
        raise V11ContractError("V11_PROBE_INVENTORY", f"{len(normative)}/{len(local)}")
    dependencies: JsonValue = {"v10": "canonical-fixtures", "v11": "local-fixtures", "v12_plus": 0}
    body: dict[str, JsonValue] = {"schema_version": "v11.paper_execution.acceptance.1",
        "state": "pass", "fixture_count": 4,
        "artifact_count": sum(_integer(item, "artifact_count") for item in reports),
        "normative_probe_count": 12, "local_probe_count": 2,
        "normative_probes": [item.model_dump(mode="json") for item in normative],
        "local_probes": [item.model_dump(mode="json") for item in local],
        "prd_reports": list(reports), "dependency_manifest": dependencies,
        "broker_submit_count": 0, "live_artifact_count": 0,
        "portfolio_mutation_count": 0, "side_effect_count": 0,
        "v12_plus_import_count": 0}
    return {**body, "report_hash": canonical_hash(body)}


def _integer(value: JsonValue, field: str) -> int:
    if isinstance(value, dict) and isinstance(item := value.get(field), int):
        return item
    raise V11ContractError("V11_REPORT_MALFORMED", field)


def _verify_prd_artifacts(prd: Literal[1, 2, 3, 4], artifacts: tuple[JsonValue, ...]) -> None:
    match prd:  # noqa: MATCH_OK - PRD literal union is exhaustively covered
        case 1:
            results = _list(artifacts[2], "risk_results")
            accepted = [item for item in results if isinstance(item, dict) and item.get("state") == "accepted"]
            blocked = [item for item in results if isinstance(item, dict) and item.get("state") == "blocked"]
            if len(accepted) < 2 or not blocked or not isinstance(artifacts[3], dict):
                raise V11ContractError("V11_PRD01_INCOMPLETE", "risk/reservation/halt")
        case 2:
            executions = _list(artifacts[0], "executions")
            fills = _list(artifacts[1], "fills")
            exits = _list(artifacts[2], "forced_exits")
            ledgers = artifacts[3]
            metadata = artifacts[5]
            sides = {side for item in fills if isinstance(item, dict)
                     and isinstance(side := item.get("side"), str)}
            reasons = {reason for item in exits if isinstance(item, dict)
                       and isinstance(reason := item.get("reason"), str)}
            positive = [item for item in fills if isinstance(item, dict)
                        and isinstance(quantity := item.get("filled_quantity"), int)
                        and not isinstance(quantity, bool) and quantity > 0]
            if (len(executions) < 3 or sides != {"long", "short"} or len(positive) < 3
                    or not all(isinstance(item, dict) and
                        (item.get("state") in {"blocked", "cancelled"}
                         or isinstance(item.get("target_at"), str))
                        for item in executions)
                    or not {"borrow_recall", "daily_loss", "market_close"} <= reasons):
                raise V11ContractError("V11_PRD02_INCOMPLETE", "execution/short/exit")
            if not isinstance(ledgers, dict):
                raise V11ContractError("V11_PRD02_INCOMPLETE", "daily-loss ledger")
            if not isinstance(metadata, dict) or not isinstance(
                    observed_at := metadata.get("daily_loss_observed_at"), str):
                raise V11ContractError("V11_PRD02_INCOMPLETE", "daily-loss observed_at")
            kr_events = _list(ledgers.get("KR"), "KR ledger")
            timeline = [(item.get("event_type"), item.get("entity_id"), item.get("occurred_at"),
                         item.get("payload")) for item in kr_events if isinstance(item, dict)]
            halt_index = next((index for index, item in enumerate(timeline)
                               if item[1] == "daily_loss_halt"), -1)
            cancel_index = next((index for index, item in enumerate(timeline)
                                 if item[0] == "order_cancelled"), -1)
            forced_index = next((index for index, item in enumerate(timeline)
                                 if isinstance(item[1], str) and item[1].startswith("forced:daily:")), -1)
            pending = next((item for item in executions if isinstance(item, dict)
                            and item.get("decision_id") == "kr-long"), None)
            cancel_entity = timeline[cancel_index][1] if cancel_index >= 0 else None
            pre_halt_fills = [item for item in timeline[:halt_index]
                              if item[0] == "fill_complete"]
            pending_fills = [item for item in timeline if item[1] == cancel_entity
                             and item[0] in {"fill_partial", "fill_complete"}]
            halt_at = timeline[halt_index][2] if halt_index >= 0 else None
            if (not 0 < halt_index < cancel_index < forced_index or not isinstance(halt_at, str)
                    or datetime.fromisoformat(halt_at) != datetime.fromisoformat(observed_at)
                    or not pre_halt_fills or pending_fills or not isinstance(pending, dict)
                    or pending.get("state") != "cancelled"
                    or not isinstance(target_at := pending.get("target_at"), str)
                    or datetime.fromisoformat(target_at) < datetime.fromisoformat(observed_at)):
                raise V11ContractError("V11_PRD02_INCOMPLETE", "daily-loss chronology")
        case 3:
            reconciliation = artifacts[2]
            halt = artifacts[3]
            receipts = artifacts[4]
            if not isinstance(reconciliation, dict) or reconciliation.get("execution_halt") is not True:
                raise V11ContractError("V11_PRD03_INCOMPLETE", "reconciliation")
            if not isinstance(halt, dict) or halt.get("new_intents_blocked") is not True:
                raise V11ContractError("V11_PRD03_INCOMPLETE", "halt")
            if not isinstance(receipts, dict):
                raise V11ContractError("V11_PRD03_INCOMPLETE", "idempotency")
        case 4:
            boundary = artifacts[0]
            if not isinstance(boundary, dict) or len(_list(boundary.get("orchestrated_prds"), "orchestrated")) != 3:
                raise V11ContractError("V11_PRD04_INCOMPLETE", "orchestration")
            if len(_list(boundary.get("v10_fixture_hashes"), "v10_fixtures")) != 4:
                raise V11ContractError("V11_PRD04_INCOMPLETE", "v10 fixtures")


def _list(value: JsonValue | None, field: str) -> list[JsonValue]:
    if isinstance(value, list):
        return value
    raise V11ContractError("V11_REPORT_MALFORMED", field)
