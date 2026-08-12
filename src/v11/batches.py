from __future__ import annotations

from decimal import Decimal

from .accounts import create_account
from .fixture_models import RiskCase
from .models import Account, Market, RiskResult
from .reservations import reserve
from .risk import check_risk
from .sizing import causal_quantity


def evaluate_batches(cases: tuple[RiskCase, ...]) -> tuple[dict[Market, Account], tuple[RiskResult, ...]]:
    accounts = {Market.KR: create_account(Market.KR), Market.US: create_account(Market.US)}
    groups: dict[tuple[Market, str], list[RiskCase]] = {}
    for case in cases:
        key = (case.decision.market, case.decision.cutoff.isoformat())
        groups.setdefault(key, []).append(case)
    results: list[RiskResult] = []
    for key in sorted(groups, key=lambda item: (item[0].value, item[1])):
        ordered = sorted(groups[key], key=lambda item: (-Decimal(item.decision.deterministic_score),
            item.decision.symbol, item.decision.decision_id))
        for case in ordered:
            account = accounts[case.decision.market]
            quantity, _ = causal_quantity(account, case.reference_price, case.historical_turnovers)
            result = check_risk(account, case.decision, quantity, case.reference_price,
                case.candidate_returns, case.existing_returns, case.gates, case.expected_cost)
            results.append(result)
            if result.reservation:
                accounts[case.decision.market] = reserve(account, result.reservation)
    return accounts, tuple(results)
