from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from src.v4.models import JsonValue, canonical_json
from src.v10.strategy_input_models import StrategyInputFixture
from src.v11.acceptance import FIXTURES as V11_FIXTURES, load_fixture as load_v11
from src.v11.canonical import canonical_hash, model_json
from src.v11.fixture_models import Prd01Fixture, Prd02Fixture
from src.v11.acceptance import build_path as build_v11
from src.v11.verifier import verify_bundle as verify_v11
from src.v11.models import Account

from .models import ArtifactRef, Bar, BorrowEligibility, BundleRef, CausalSizingObservation, CohortFixture, ExecutionBinding, ExecutionInputs, ExecutionSnapshot, FixtureCase, HistoricalValue, Market, Scenario, StrategyInput, StrategySpec
from .registry import REGISTRY
from .strategy_input_fixture import bind_cases, build_source_fixture


_SESSION = date(2026, 1, 5)
_OPEN = datetime(2026, 1, 5, tzinfo=timezone.utc)
_BUNDLES = {
    "v10-1": "sha256:476248d11a9ea1b845ac95849d0873986fcbe455c52680fcf6af22a0d4a8b671",
    "v10-2": "sha256:bd7885509333be775f39bcc8c45070e4d9f6ead0062f7b1ec5fd2b03a83e10f4",
    "v10-3": "sha256:ffd28befab287922878c7907fd362f3bad6caed22af3cfae994e7b539ce527ec",
    "v11-1": "sha256:b4cfcff86d82987af0a7e1ac0ae7b57e99ab40cfd641901791074e47eb7e4303",
    "v11-2": "sha256:f45b2038c88ecce6ad064981eda67b98a9ec16ab9f3d15b81d9e8a020bc637f3",
}
_FIVE = ArtifactRef(artifact_type="five_minute_bar",
    artifact_id="v10:five_minute_bar:aa61816fe013819bbaba",
    content_hash="sha256:aa61816fe013819bbabaa3e3fde1299ede2b51b3bfaa72b660ee2999aac60b65",
    bundle_hash=_BUNDLES["v10-2"])
_CALENDAR = ArtifactRef(artifact_type="market_calendar_snapshot",
    artifact_id="v10:market_calendar_snapshot:f7ef7cc73c322c1d09ff",
    content_hash="sha256:f7ef7cc73c322c1d09ffe17496528229931554e920075c4d3b57475b2c524da0",
    bundle_hash=_BUNDLES["v10-1"])
_UNIVERSE = ArtifactRef(artifact_type="universe_snapshot",
    artifact_id="v10:universe_snapshot:84cd7957bfda90c127e4",
    content_hash="sha256:84cd7957bfda90c127e4600a58c75c3523c18e77b1918823c41b1be79c3f3257",
    bundle_hash=_BUNDLES["v10-3"])
_ADJUSTMENT = ArtifactRef(artifact_type="price_adjustment_snapshot",
    artifact_id="v10:price_adjustment_snapshot:0348efab805656d608ad",
    content_hash="sha256:0348efab805656d608addaa5381442808a6edc4d45b527f114c3e80f168371a3",
    bundle_hash=_BUNDLES["v10-3"])
_V11_ACCOUNT = ArtifactRef(artifact_type="v11_bundle_artifact", artifact_id="v11:1:0",
    content_hash="sha256:9b141723a42118ee991805a1a4489ed0a1f7bb9b9fa3c7024695e68937365a69",
    bundle_hash=_BUNDLES["v11-1"])
_V11_EXECUTION = ArtifactRef(artifact_type="v11_bundle_artifact", artifact_id="v11:2:5",
    content_hash="sha256:2dacea6ff11d40602b9c4436b6ced52047e2c42b943da71a36f298b4901da36b",
    bundle_hash=_BUNDLES["v11-2"])
_STRATEGY_INPUT_PATH = "docs/specs/v10/fixtures/strategy-input-v12.json"


def _bar(index: int, upward: bool, ref: ArtifactRef, complete: bool = True) -> Bar:
    base = Decimal(100) + Decimal(index) * Decimal("0.08") * (1 if upward else -1)
    start = _OPEN + timedelta(minutes=index * 5)
    end = start + timedelta(minutes=5)
    return Bar(ref=ref, source_ref=_FIVE, calendar_ref=_CALENDAR,
        session_date=_SESSION, start=start, end=end,
        open=base - Decimal("0.03"), high=base + Decimal("0.20"),
        low=base - Decimal("0.20"), close=base, volume=100, complete=complete,
        observed_at=end + timedelta(seconds=5), watermark_at=end + timedelta(seconds=10),
        adjustment_factor=Decimal("0.50"))


def _history(slot: int) -> dict[str, tuple[HistoricalValue, ...]]:
    keys = ("distance", "rvol", "gap", "clv", "spread", "price", "rs", "ret",
            "expansion", "compression")
    slots = (slot - 5, slot)
    return {key: tuple(HistoricalValue(session_date=date(2025, 9, 1) + timedelta(days=index),
        minute_slot=minute_slot, value=Decimal(index + 1) / Decimal(100))
        for minute_slot in slots for index in range(70))
        for key in keys}


def _input(spec: StrategySpec, scenario: Scenario) -> StrategyInput:
    upward = spec.side.value == "long"
    count = 12 if spec.evaluator == "orb15" else 18 if spec.evaluator == "orb30" else 40
    bars = tuple(_bar(index, upward, _FIVE, scenario is not Scenario.MISSING or index != count - 1)
                 for index in range(count))
    move = Decimal(4) * (1 if upward else -1)
    close = bars[-1].close + move
    bars = (*bars[:-1], bars[-1].model_copy(update={"open": close, "high": close + Decimal("0.2"),
        "low": close - Decimal("0.2"), "close": close, "volume": 300}))
    if spec.evaluator == "compression":
        tight = tuple(item.model_copy(update={"open": Decimal(100), "high": Decimal("100.05"),
            "low": Decimal("99.95"), "close": Decimal(100)}) for item in bars[-7:-1])
        bars = (*bars[:-7], *tight, bars[-1])
    if spec.evaluator == "expansion":
        current = bars[-1]
        bars = (*bars[:-1], current.model_copy(update={"high": current.close + Decimal("0.02"),
            "low": current.close - Decimal("1.5")}))
    if spec.evaluator == "vwap":
        prior = Decimal(95) if upward else Decimal(105)
        changed = tuple(item.model_copy(update={"open": prior, "high": prior + Decimal("0.1"),
            "low": prior - Decimal("0.1"), "close": prior}) for item in bars[-3:-1])
        bars = (*bars[:-3], *changed, bars[-1])
    if spec.evaluator == "rs":
        rising = tuple(item.model_copy(update={"open": Decimal(100) + index,
            "high": Decimal("100.2") + index, "low": Decimal("99.8") + index,
            "close": Decimal(100) + index}) for index, item in enumerate(bars))
        bars = (*rising[:-1], rising[-1].model_copy(update={"open": Decimal(300),
            "high": Decimal("300.2"), "low": Decimal("299.8"), "close": Decimal(300)}))
    if scenario is Scenario.NO_SIGNAL:
        bars = tuple(item.model_copy(update={"open": Decimal(100), "high": Decimal("100.1"),
            "low": Decimal("99.9"), "close": Decimal(100), "volume": 100}) for item in bars)
    prior_start = _OPEN - timedelta(days=3, minutes=100)
    prior = tuple(_bar(index, upward, _FIVE).model_copy(update={"session_date": date(2026, 1, 2),
        "start": prior_start + timedelta(minutes=index * 5),
        "end": prior_start + timedelta(minutes=(index + 1) * 5),
        "observed_at": prior_start + timedelta(minutes=(index + 1) * 5, seconds=5),
        "watermark_at": prior_start + timedelta(minutes=(index + 1) * 5, seconds=10)})
        for index in range(20))
    benchmark = tuple(item.model_copy(update={"open": Decimal(100), "high": Decimal("100.1"),
        "low": Decimal("99.9"), "close": Decimal(100), "volume": 100}) for item in bars)
    target = bars[-1].end + timedelta(minutes=1)
    snapshot_body: dict[str, JsonValue] = {"target_at": target.isoformat(), "open": "100",
        "volume": 2000, "source_ref": model_json(_FIVE), "calendar_ref": model_json(_CALENDAR),
        "watermark_ref": model_json(_FIVE)}
    snapshot = ExecutionSnapshot(target_at=target, open=Decimal(100), volume=2000,
        source_ref=_FIVE, calendar_ref=_CALENDAR, watermark_ref=_FIVE,
        snapshot_hash=canonical_hash(snapshot_body))
    risk_kill_at = (_OPEN + timedelta(hours=2, seconds=15)
        if spec.strategy_id in {"long_orb_15m", "short_orb_15m"}
        and scenario is Scenario.HAPPY else None)
    borrow = BorrowEligibility(market=Market.KR, symbol="KR:000001",
        effective_from=_OPEN, effective_until=_OPEN + timedelta(days=1),
        evaluated_at=_OPEN,
        recalled_at=((_OPEN + timedelta(hours=3, seconds=30)
            if spec.strategy_id == "short_orb_15m" else _OPEN + timedelta(hours=4, seconds=30))
            if spec.strategy_id in {"short_orb_15m", "short_gap_continuation"}
            and scenario is Scenario.HAPPY else None),
        annual_fee=Decimal("0.1"),
        locate=True, etb=True,
        shortable=True, regulation_known=True, refs=(_V11_EXECUTION,))
    causal = CausalSizingObservation(observed_at=bars[-1].end,
        close=bars[-1].close, prior_turnovers=tuple(Decimal(value)
            for value in ("100000000",) * 20))
    bindings = tuple(ExecutionBinding(cutoff=bar.end,
        causal_sizing=CausalSizingObservation(observed_at=bar.end, close=bar.close,
            prior_turnovers=causal.prior_turnovers),
        execution_snapshot=snapshot.model_copy(update={"target_at": bar.end + timedelta(minutes=1)}))
        for bar in bars)
    return StrategyInput(market=Market.KR, symbol="KR:000001", sector="technology",
        benchmark_id="KR_BROAD_KS11", session_date=_SESSION, regular_open=_OPEN,
        regular_close=_OPEN + timedelta(hours=6, minutes=30),
        watermark_at=bars[-1].end + timedelta(seconds=10), adjustment_factor=Decimal("0.50"),
        previous_adjusted_close=Decimal(104) if not upward else Decimal(96),
        risk_kill_at=risk_kill_at, bars=bars,
        prior_bars=prior, benchmark_bars=benchmark, historical=_history(count * 5),
        eligibility_refs=(_UNIVERSE, _ADJUSTMENT), borrow=borrow,
        causal_sizing=causal, execution_snapshot=snapshot, execution_bindings=bindings)


def _series_id(spec: StrategySpec, scenario: Scenario) -> str:
    return f"{spec.strategy_id}:{scenario.value}"


def strategy_input_fixture() -> StrategyInputFixture:
    inputs = tuple((_series_id(spec, scenario), _input(spec, scenario))
                   for spec in REGISTRY for scenario in Scenario)
    return build_source_fixture(inputs)


def fixture() -> CohortFixture:
    prd01 = Prd01Fixture.model_validate(load_v11(V11_FIXTURES[1]))
    prd02 = Prd02Fixture.model_validate(load_v11(V11_FIXTURES[2]))
    def expected_result(scenario: Scenario) -> Literal["candidate", "no_signal", "missing_feature"]:
        match scenario:  # noqa: MATCH_OK - Scenario enum is exhaustively covered
            case Scenario.HAPPY: return "candidate"
            case Scenario.NO_SIGNAL: return "no_signal"
            case Scenario.MISSING: return "missing_feature"
    cases = tuple(FixtureCase(strategy_id=spec.strategy_id, scenario=scenario,
        expected_result=expected_result(scenario), input=_input(spec, scenario))
        for spec in REGISTRY for scenario in Scenario)
    cases, strategy_input_hash = bind_cases(cases, strategy_input_fixture())
    bundles = (
        BundleRef(version="v10", path="docs/specs/v10/fixtures/prd01-calendar-minute.json",
            bundle_hash=_BUNDLES["v10-1"], artifact_refs=(_CALENDAR,)),
        BundleRef(version="v10", path="docs/specs/v10/fixtures/prd02-aggregation-revision.json",
            bundle_hash=_BUNDLES["v10-2"], artifact_refs=(_FIVE,)),
        BundleRef(version="v10", path="docs/specs/v10/fixtures/prd03-universe-actions.json",
            bundle_hash=_BUNDLES["v10-3"], artifact_refs=(_UNIVERSE, _ADJUSTMENT)),
        BundleRef(version="v10_strategy_input", path=_STRATEGY_INPUT_PATH,
            bundle_hash=strategy_input_hash, artifact_refs=()),
        BundleRef(version="v11", path="docs/specs/v11/fixtures/prd01.json",
            bundle_hash=_BUNDLES["v11-1"], artifact_refs=(_V11_ACCOUNT,)),
        BundleRef(version="v11", path="docs/specs/v11/fixtures/prd02.json",
            bundle_hash=_BUNDLES["v11-2"], artifact_refs=(_V11_EXECUTION,)),
    )
    account_bundle = verify_v11(canonical_json(build_v11(V11_FIXTURES[1])))
    execution = ExecutionInputs(account=Account.model_validate(account_bundle.artifacts[0]),
        historical_turnovers=prd01.cases[2].historical_turnovers,
        gates=prd01.cases[2].gates, cost_policy=prd02.cost_policy)
    expected_ids = tuple(sorted(f"{spec.strategy_id}:{scenario.value}" for spec in REGISTRY for scenario in Scenario))
    return CohortFixture(schema_version="v12.strategy.fixture.2", upstream_bundles=bundles,
        cases=cases, expected_case_ids=expected_ids, execution=execution)


def fixture_json() -> JsonValue:
    return model_json(fixture())
