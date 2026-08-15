from __future__ import annotations

from pathlib import Path

from src.v11.models import Account, Market

from src.v13.models import RecordedCandidateFixture, RouterPolicy, RouterRunManifest


FIXTURE_PATH = (
    Path(__file__).parents[2]
    / "docs"
    / "specs"
    / "v13"
    / "fixtures"
    / "prd01-candidates.json"
)


def load_fixture() -> RecordedCandidateFixture:
    return RecordedCandidateFixture.model_validate_json(FIXTURE_PATH.read_bytes())


def canonical_account() -> Account:
    return Account(
        market=Market.KR,
        currency="KRW",
        prior_close_nav="100000",
        cash="100000",
    )


def manifest_for(
    fixture: RecordedCandidateFixture, policy: RouterPolicy
) -> RouterRunManifest:
    return RouterRunManifest(
        schema_version="v13.router_run.1",
        run_id="prd01:canonical",
        market=Market.KR,
        cutoff=fixture.candidates[0].cutoff,
        policy=policy,
        account=canonical_account(),
        candidates=fixture.candidates,
        slot_limit=2,
    )
