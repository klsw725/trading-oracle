from __future__ import annotations

from .models import CohortFixture, Scenario, V12ContractError
from .registry import REGISTRY


def validate_fixture_matrix(fixture: CohortFixture) -> None:
    expected = {f"{spec.strategy_id}:{scenario.value}" for spec in REGISTRY for scenario in Scenario}
    observed = {f"{case.strategy_id}:{case.scenario.value}" for case in fixture.cases}
    declared = set(fixture.expected_case_ids)
    if len(fixture.cases) != 45 or len(observed) != 45:
        raise V12ContractError("V12_CASE_MATRIX_COUNT", str(len(observed)))
    if observed != expected or declared != expected or len(fixture.expected_case_ids) != 45:
        raise V12ContractError("V12_CASE_MATRIX_IDENTITY", str(sorted(expected ^ observed)))
    for case in fixture.cases:
        expected_result = {Scenario.HAPPY: "candidate", Scenario.NO_SIGNAL: "no_signal",
            Scenario.MISSING: "missing_feature"}[case.scenario]
        if case.expected_result != expected_result:
            raise V12ContractError("V12_CASE_EXPECTATION", case.strategy_id)
