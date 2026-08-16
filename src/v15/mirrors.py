from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from src.v11.canonical import canonical_hash, model_json, money
from src.v11.models import Account, Market

from .contract import StrictModel, V15Failure, V15FailureCode


class MirrorAccount(StrictModel):
    schema_version: Literal["v15.mirror_account.2"]
    account_namespace: str
    slot_namespace: str
    position_namespace: str
    market: Literal["KR", "US"]
    arm: Literal["orb", "router"]
    comparison_epoch_start: date
    initial_account: Account
    market_data_hash: str
    universe_hash: str
    risk_version: str
    cost_model: str
    account_hash: str


class MirrorSetup(StrictModel):
    market: Literal["KR", "US"]
    epoch: date
    data_hash: str
    universe_hash: str
    risk_version: str
    cost_model: str


def create_mirrors(
    identity: tuple[Literal["KR", "US"], date],
    initial_nav: Decimal,
    evidence: tuple[str, str, str, str],
) -> tuple[MirrorAccount, MirrorAccount]:
    market, epoch = identity
    data_hash, universe_hash, risk_version, cost_model = evidence
    account = Account(market=Market(market),
        currency="KRW" if market == "KR" else "USD",
        prior_close_nav=money(initial_nav), cash=money(initial_nav))
    setup = MirrorSetup(market=market, epoch=epoch, data_hash=data_hash,
        universe_hash=universe_hash, risk_version=risk_version,
        cost_model=cost_model)
    accounts = tuple(_mirror(account, setup, arm)
        for arm in ("orb", "router"))
    result = (accounts[0], accounts[1])
    verify_isolation(result)
    return result


def _mirror(
    account: Account,
    setup: MirrorSetup,
    arm: Literal["orb", "router"],
) -> MirrorAccount:
    prefix = f"v15:{setup.market}:{setup.epoch.isoformat()}:{arm}"
    draft = MirrorAccount(schema_version="v15.mirror_account.2",
        account_namespace=f"{prefix}:account", slot_namespace=f"{prefix}:slot",
        position_namespace=f"{prefix}:position", market=setup.market, arm=arm,
        comparison_epoch_start=setup.epoch, initial_account=account,
        market_data_hash=setup.data_hash, universe_hash=setup.universe_hash,
        risk_version=setup.risk_version, cost_model=setup.cost_model,
        account_hash="")
    return draft.model_copy(update={"account_hash": canonical_hash(
        model_json(draft.model_copy(update={"account_hash": ""})))})


def verify_isolation(accounts: tuple[MirrorAccount, MirrorAccount]) -> None:
    orb, router = accounts
    orb_names = {orb.account_namespace, orb.slot_namespace, orb.position_namespace}
    router_names = {router.account_namespace, router.slot_namespace,
        router.position_namespace}
    if orb_names & router_names or orb.account_hash == router.account_hash:
        raise V15Failure(V15FailureCode.MIRROR_NOT_ISOLATED, "namespace")
    shared = (orb.market, orb.comparison_epoch_start, orb.initial_account,
        orb.market_data_hash, orb.universe_hash, orb.risk_version, orb.cost_model)
    if shared != (router.market, router.comparison_epoch_start,
            router.initial_account, router.market_data_hash, router.universe_hash,
            router.risk_version, router.cost_model):
        raise V15Failure(V15FailureCode.MIRROR_NOT_ISOLATED, "inputs")
