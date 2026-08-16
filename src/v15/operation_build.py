from __future__ import annotations

from src.v11.canonical import canonical_hash, model_json

from .activation import approve_activation
from .approvals import verify_manual_approval_consumption
from .effects import EffectKind, EffectRecord, build_effect_ledger
from .fixtures import verify_v14_path
from .market_operation import build_market_operation
from .operation_events import build_events
from .operation_fixture import OperationSourceFixture, verify_source
from .operation_kills import build_kill_inventory
from .operation_models import (
    OperationBundle,
    OperationBundleBody,
    OperationMaterial,
)
from .operation_replay import replay
from .operation_reports import build_reports
from .operation_scenarios import build_llm_outcomes
from .retirement import (
    RetirementBody,
    append_retirement,
    verify_registry,
)
from .upstream import UpstreamEvidence


def build_operation_bundle(
    source: OperationSourceFixture, verified_upstream: UpstreamEvidence | None = None
) -> OperationBundle:
    verify_source(source)
    upstream = verify_v14_path(source.v14_artifact) \
        if verified_upstream is None else verified_upstream
    verify_registry(source.prior_retirement_registry)
    markets = tuple(build_market_operation(source, timeline, upstream,
        source.prior_retirement_registry)
        for timeline in source.markets)
    market_operations = (markets[0], markets[1])
    kills = build_kill_inventory(source, market_operations, upstream)
    market_operations = kills.markets
    approvals = tuple(approve_activation(item, source, upstream)
        for item in market_operations)
    typed_approvals = (approvals[0], approvals[1])
    registry = source.prior_retirement_registry
    for market in sorted(market_operations,
            key=lambda item: item.schedule.comparison_sessions[-1]):
        rollback = market.performance_rollback
        if rollback is None:
            continue
        registry = append_retirement(registry, RetirementBody(
            schema_version="v15.retirement_record.1",
            sequence=len(registry.records) + 1, market=market.market,
            router_version=source.policy_version,
            manifest_hash=upstream.policy.manifest_hash,
            retired_session=market.schedule.comparison_sessions[-1],
            evidence_hash=rollback.evidence_hash,
            previous_hash=registry.tail_hash))
    consumed = tuple(item for item in typed_approvals if not item.automatic) \
        + tuple(item.approval for item in kills.recoveries
            if item.approval is not None)
    verify_manual_approval_consumption(source.manual_approvals, consumed)
    llm = build_llm_outcomes(market_operations)
    reports = build_reports(market_operations, llm, kills.incidents,
        kills.executions, kills.recoveries, upstream.policy.manifest_hash,
        source.policy_version)
    events = build_events(market_operations, typed_approvals,
        kills.executions, kills.incidents, kills.recoveries, registry,
        upstream.policy.manifest_hash)
    source_hash = canonical_hash(model_json(source))
    effects = build_effect_ledger((EffectRecord(
        kind=EffectKind.LOCAL_FIXTURE_READ, target_hash=source_hash),
        EffectRecord(kind=EffectKind.LOCAL_FIXTURE_READ,
            target_hash=upstream.v14_bundle_hash),
        *(EffectRecord(kind=EffectKind.LOCAL_FIXTURE_READ,
            target_hash=item.calendar_fixture_hash) for item in source.markets)))
    material = OperationMaterial(schema_version="v15.operation_bundle.2",
        source=source, source_fixture_hash=source_hash, upstream=upstream,
        approvals=typed_approvals, markets=market_operations,
        pnl_marks=kills.pnl_marks, loss_results=kills.loss_results,
        kill_executions=kills.executions, incidents=kills.incidents,
        recoveries=kills.recoveries, retirement_registry=registry,
        events=events, llm_outcomes=llm, session_reports=reports,
        effects=effects)
    replayed = replay(material)
    body = OperationBundleBody(schema_version=material.schema_version,
        source=material.source, source_fixture_hash=material.source_fixture_hash,
        upstream=material.upstream, approvals=material.approvals,
        markets=material.markets, pnl_marks=material.pnl_marks,
        loss_results=material.loss_results,
        kill_executions=material.kill_executions,
        incidents=material.incidents, recoveries=material.recoveries,
        retirement_registry=material.retirement_registry,
        events=material.events, llm_outcomes=material.llm_outcomes,
        session_reports=material.session_reports, effects=material.effects,
        replay=replayed)
    return OperationBundle(schema_version=body.schema_version,
        source=body.source, source_fixture_hash=body.source_fixture_hash,
        upstream=body.upstream, approvals=body.approvals,
        markets=body.markets, pnl_marks=body.pnl_marks,
        loss_results=body.loss_results,
        kill_executions=body.kill_executions, incidents=body.incidents,
        recoveries=body.recoveries,
        retirement_registry=body.retirement_registry, events=body.events,
        llm_outcomes=body.llm_outcomes, session_reports=body.session_reports,
        effects=body.effects, replay=body.replay,
        bundle_hash=canonical_hash(model_json(body)))
