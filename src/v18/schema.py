from typing import Final

SCHEMA_HEAD: Final = 2
MEASUREMENT_EVENT_SCHEMA_VERSION: Final = "v18.measurement-event.1"
GENESIS_HASH: Final = "sha256:" + "0" * 64

V17_TABLES: Final = (
    "schema_migrations",
    "accounts",
    "events",
    "idempotency_keys",
    "account_balances",
    "account_positions",
    "account_reservations",
    "projection_checkpoints",
)

MEASUREMENT_TABLES: Final = (
    "predictions",
    "legacy_prediction_quarantine",
    "measurement_events",
    "outcome_evaluations",
    "cohort_manifests",
    "policy_candidates",
    "candidate_events",
    "measurement_idempotency",
)

TABLES: Final = V17_TABLES + MEASUREMENT_TABLES

TRIGGERS: Final = (
    "candidate_events_immutable_delete",
    "candidate_events_immutable_update",
    "cohort_manifests_immutable_delete",
    "cohort_manifests_immutable_update",
    "events_immutable_delete",
    "events_immutable_update",
    "legacy_quarantine_immutable_delete",
    "legacy_quarantine_immutable_update",
    "measurement_events_immutable_delete",
    "measurement_events_immutable_update",
    "measurement_idempotency_immutable_delete",
    "measurement_idempotency_immutable_update",
    "outcome_evaluations_immutable_delete",
    "outcome_evaluations_immutable_update",
    "policy_candidates_body_immutable_update",
    "policy_candidates_immutable_delete",
    "policy_candidates_state_transition",
    "predictions_body_immutable_update",
    "predictions_immutable_delete",
    "predictions_state_transition",
)
