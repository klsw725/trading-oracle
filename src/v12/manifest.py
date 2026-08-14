from __future__ import annotations

from src.v4.models import JsonValue
from src.v11.canonical import canonical_hash, model_json
from src.v11.costs import freeze_policy

from .artifacts import ArmManifest
from .models import CohortFixture
from .registry import REGISTRY


def registry_hash() -> str:
    return canonical_hash([model_json(item) for item in REGISTRY])


def build_manifests(fixture: CohortFixture, source_hash: str) -> tuple[ArmManifest, ...]:
    policy = freeze_policy(fixture.execution.cost_policy,
                           fixture.cases[0].input.session_date.isoformat())
    registry_digest = registry_hash()
    manifests: list[ArmManifest] = []
    for spec in REGISTRY:
        for parameters in spec.parameter_sets:
            arm_id = f"v12:arm:{spec.strategy_id}:{parameters.parameter_set_id}"
            owner = f"shadow/{fixture.cases[0].input.market.value}/{spec.strategy_id}/{parameters.parameter_set_id}"
            account_arm = f"v12-account:{canonical_hash({'arm_id': arm_id, 'owner': owner})[7:27]}"
            body: dict[str, JsonValue] = {"arm_id": arm_id, "account_arm_id": account_arm,
                "owner_namespace": owner, "strategy_id": spec.strategy_id,
                "strategy_version": spec.version,
                "active_parameter_set_id": parameters.parameter_set_id,
                "source_fixture_hash": source_hash, "registry_hash": registry_digest,
                "cost_policy_hash": policy.policy_hash}
            manifests.append(ArmManifest(arm_id=arm_id, account_arm_id=account_arm,
                owner_namespace=owner, strategy_id=spec.strategy_id,
                strategy_version=spec.version,
                active_parameter_set_id=parameters.parameter_set_id,
                source_fixture_hash=source_hash, registry_hash=registry_digest,
                cost_policy_hash=policy.policy_hash, manifest_hash=canonical_hash(body)))
    return tuple(manifests)
