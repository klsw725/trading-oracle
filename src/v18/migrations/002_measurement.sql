CREATE TABLE predictions (
 prediction_id TEXT PRIMARY KEY, recommendation_id TEXT NOT NULL UNIQUE,
 market TEXT NOT NULL, currency TEXT NOT NULL, account_id TEXT NOT NULL, arm_id TEXT NOT NULL, symbol TEXT NOT NULL,
 prediction_session TEXT NOT NULL, horizon_sessions INTEGER NOT NULL CHECK (horizon_sessions>0),
 action TEXT NOT NULL CHECK (action IN ('BUY','HOLD','SELL')), reference_price_minor INTEGER NOT NULL CHECK (reference_price_minor>0),
 runtime_identity TEXT NOT NULL, config_version TEXT NOT NULL, source_policy_version TEXT NOT NULL,
 calendar_version TEXT NOT NULL, calendar_hash TEXT NOT NULL, price_adjustment_version TEXT NOT NULL,
 perspective_scores_json TEXT NOT NULL, perspective_scores_as_of TEXT NOT NULL,
 source_payload_hash TEXT NOT NULL, recorded_as_of TEXT NOT NULL,
 body_json TEXT NOT NULL, body_hash TEXT NOT NULL UNIQUE,
 current_state TEXT NOT NULL CHECK (current_state IN ('REGISTERED','MATURE','EVALUATED')),
 target_session TEXT, target_price_minor INTEGER, outcome_id TEXT,
 registration_event_id TEXT NOT NULL UNIQUE,
 CHECK ((market='KR' AND currency='KRW') OR (market='US' AND currency='USD')),
 CHECK ((current_state='REGISTERED' AND target_session IS NULL AND target_price_minor IS NULL AND outcome_id IS NULL)
     OR (current_state='MATURE' AND target_session IS NOT NULL AND target_price_minor IS NOT NULL AND outcome_id IS NULL)
     OR (current_state='EVALUATED' AND target_session IS NOT NULL AND target_price_minor IS NOT NULL AND outcome_id IS NOT NULL))
);
CREATE TABLE legacy_prediction_quarantine (
 quarantine_id TEXT PRIMARY KEY, source_label TEXT NOT NULL, source_bytes_hash TEXT NOT NULL,
 observed_schema_hint TEXT NOT NULL, rejection_codes_json TEXT NOT NULL, observed_as_of TEXT NOT NULL,
 body_json TEXT NOT NULL, body_hash TEXT NOT NULL UNIQUE, event_id TEXT NOT NULL UNIQUE,
 UNIQUE (source_label,source_bytes_hash,observed_as_of)
);
CREATE TABLE measurement_events (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
 event_schema_version TEXT NOT NULL, event_type TEXT NOT NULL, aggregate_id TEXT NOT NULL,
 semantic_key TEXT NOT NULL UNIQUE, payload_json TEXT NOT NULL, previous_event_hash TEXT NOT NULL,
 event_hash TEXT NOT NULL UNIQUE, created_as_of TEXT NOT NULL
);
CREATE TABLE outcome_evaluations (
 outcome_id TEXT PRIMARY KEY, prediction_id TEXT NOT NULL UNIQUE,
 target_session TEXT NOT NULL, target_adjusted_price_minor INTEGER NOT NULL CHECK (target_adjusted_price_minor>0),
 return_bps INTEGER NOT NULL, verdict TEXT NOT NULL CHECK (verdict IN ('CORRECT','INCORRECT','NEUTRAL')),
 maturity_as_of TEXT NOT NULL, evaluator_policy_version TEXT NOT NULL,
 calendar_hash TEXT NOT NULL, price_dataset_hash TEXT NOT NULL,
 body_json TEXT NOT NULL, body_hash TEXT NOT NULL UNIQUE, event_id TEXT NOT NULL UNIQUE,
 FOREIGN KEY (prediction_id) REFERENCES predictions(prediction_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE cohort_manifests (
 cohort_id TEXT PRIMARY KEY, market TEXT NOT NULL, currency TEXT NOT NULL,
 account_id TEXT NOT NULL, arm_id TEXT NOT NULL, horizon_sessions INTEGER NOT NULL,
 source_policy_version TEXT NOT NULL, evaluator_policy_version TEXT NOT NULL,
 calendar_version TEXT NOT NULL, price_adjustment_version TEXT NOT NULL,
 eligibility_policy_version TEXT NOT NULL, cutoff_as_of TEXT NOT NULL,
 member_ids_json TEXT NOT NULL, decisions_json TEXT NOT NULL, outcome_hashes_json TEXT NOT NULL,
 body_json TEXT NOT NULL, manifest_hash TEXT NOT NULL UNIQUE, event_id TEXT NOT NULL UNIQUE,
 CHECK ((market='KR' AND currency='KRW') OR (market='US' AND currency='USD'))
);
CREATE TABLE policy_candidates (
 candidate_id TEXT PRIMARY KEY, candidate_version TEXT NOT NULL,
 base_policy_version TEXT NOT NULL, market TEXT NOT NULL, currency TEXT NOT NULL,
 account_id TEXT NOT NULL, arm_id TEXT NOT NULL, cohort_id TEXT NOT NULL,
 objective_version TEXT NOT NULL, weights_json TEXT NOT NULL,
 effective_session TEXT NOT NULL, created_as_of TEXT NOT NULL, evidence_hash TEXT NOT NULL,
 body_json TEXT NOT NULL, body_hash TEXT NOT NULL UNIQUE,
 current_status TEXT NOT NULL CHECK (current_status IN ('PROPOSED','APPROVED','SCHEDULED','REJECTED','ROLLED_BACK')),
 proposal_event_id TEXT NOT NULL UNIQUE,
 UNIQUE (market,currency,account_id,arm_id,candidate_version),
 CHECK ((market='KR' AND currency='KRW') OR (market='US' AND currency='USD')),
 FOREIGN KEY (cohort_id) REFERENCES cohort_manifests(cohort_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE candidate_events (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_schema_version TEXT NOT NULL CHECK (event_schema_version='v18.policy-candidate-event.1'),
 event_id TEXT NOT NULL UNIQUE,
 candidate_id TEXT NOT NULL, event_type TEXT NOT NULL, decision_id TEXT NOT NULL UNIQUE,
 previous_event_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE,
 transition_as_of TEXT NOT NULL, rollback_of_candidate_id TEXT,
 payload_json TEXT NOT NULL,
 FOREIGN KEY (candidate_id) REFERENCES policy_candidates(candidate_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE measurement_idempotency (
 command_type TEXT NOT NULL, semantic_key TEXT NOT NULL, request_hash TEXT NOT NULL,
 result_json TEXT NOT NULL, result_hash TEXT NOT NULL, event_id TEXT NOT NULL,
 PRIMARY KEY (command_type,semantic_key)
);
CREATE TRIGGER predictions_body_immutable_update BEFORE UPDATE ON predictions
WHEN OLD.prediction_id IS NOT NEW.prediction_id OR OLD.recommendation_id IS NOT NEW.recommendation_id
 OR OLD.market IS NOT NEW.market OR OLD.currency IS NOT NEW.currency
 OR OLD.account_id IS NOT NEW.account_id OR OLD.arm_id IS NOT NEW.arm_id OR OLD.symbol IS NOT NEW.symbol
 OR OLD.prediction_session IS NOT NEW.prediction_session OR OLD.horizon_sessions IS NOT NEW.horizon_sessions
 OR OLD.action IS NOT NEW.action OR OLD.reference_price_minor IS NOT NEW.reference_price_minor
 OR OLD.runtime_identity IS NOT NEW.runtime_identity OR OLD.config_version IS NOT NEW.config_version
 OR OLD.source_policy_version IS NOT NEW.source_policy_version OR OLD.calendar_version IS NOT NEW.calendar_version
 OR OLD.calendar_hash IS NOT NEW.calendar_hash OR OLD.price_adjustment_version IS NOT NEW.price_adjustment_version
 OR OLD.perspective_scores_json IS NOT NEW.perspective_scores_json
 OR OLD.perspective_scores_as_of IS NOT NEW.perspective_scores_as_of
 OR OLD.source_payload_hash IS NOT NEW.source_payload_hash OR OLD.recorded_as_of IS NOT NEW.recorded_as_of
 OR OLD.body_json IS NOT NEW.body_json OR OLD.body_hash IS NOT NEW.body_hash
 OR OLD.registration_event_id IS NOT NEW.registration_event_id
BEGIN SELECT RAISE(ABORT, 'prediction body is immutable'); END;
CREATE TRIGGER predictions_state_transition BEFORE UPDATE ON predictions
WHEN NOT ((OLD.current_state='REGISTERED' AND NEW.current_state='MATURE'
           AND OLD.target_session IS NULL AND NEW.target_session IS NOT NULL
           AND OLD.target_price_minor IS NULL AND NEW.target_price_minor IS NOT NULL
           AND OLD.outcome_id IS NULL AND NEW.outcome_id IS NULL)
       OR (OLD.current_state='MATURE' AND NEW.current_state='EVALUATED'
           AND OLD.target_session IS NEW.target_session
           AND OLD.target_price_minor IS NEW.target_price_minor
           AND OLD.outcome_id IS NULL AND NEW.outcome_id IS NOT NULL))
BEGIN SELECT RAISE(ABORT, 'invalid prediction state transition'); END;
CREATE TRIGGER predictions_immutable_delete BEFORE DELETE ON predictions
BEGIN SELECT RAISE(ABORT, 'predictions are immutable'); END;
CREATE TRIGGER legacy_quarantine_immutable_update BEFORE UPDATE ON legacy_prediction_quarantine
BEGIN SELECT RAISE(ABORT, 'legacy quarantine is immutable'); END;
CREATE TRIGGER legacy_quarantine_immutable_delete BEFORE DELETE ON legacy_prediction_quarantine
BEGIN SELECT RAISE(ABORT, 'legacy quarantine is immutable'); END;
CREATE TRIGGER measurement_events_immutable_update BEFORE UPDATE ON measurement_events
BEGIN SELECT RAISE(ABORT, 'measurement events are immutable'); END;
CREATE TRIGGER measurement_events_immutable_delete BEFORE DELETE ON measurement_events
BEGIN SELECT RAISE(ABORT, 'measurement events are immutable'); END;
CREATE TRIGGER outcome_evaluations_immutable_update BEFORE UPDATE ON outcome_evaluations
BEGIN SELECT RAISE(ABORT, 'outcomes are immutable'); END;
CREATE TRIGGER outcome_evaluations_immutable_delete BEFORE DELETE ON outcome_evaluations
BEGIN SELECT RAISE(ABORT, 'outcomes are immutable'); END;
CREATE TRIGGER cohort_manifests_immutable_update BEFORE UPDATE ON cohort_manifests
BEGIN SELECT RAISE(ABORT, 'cohorts are immutable'); END;
CREATE TRIGGER cohort_manifests_immutable_delete BEFORE DELETE ON cohort_manifests
BEGIN SELECT RAISE(ABORT, 'cohorts are immutable'); END;
CREATE TRIGGER policy_candidates_body_immutable_update BEFORE UPDATE ON policy_candidates
WHEN OLD.candidate_id IS NOT NEW.candidate_id OR OLD.candidate_version IS NOT NEW.candidate_version
 OR OLD.base_policy_version IS NOT NEW.base_policy_version OR OLD.market IS NOT NEW.market
 OR OLD.currency IS NOT NEW.currency OR OLD.account_id IS NOT NEW.account_id
 OR OLD.arm_id IS NOT NEW.arm_id OR OLD.cohort_id IS NOT NEW.cohort_id
 OR OLD.objective_version IS NOT NEW.objective_version OR OLD.weights_json IS NOT NEW.weights_json
 OR OLD.effective_session IS NOT NEW.effective_session OR OLD.created_as_of IS NOT NEW.created_as_of
 OR OLD.evidence_hash IS NOT NEW.evidence_hash OR OLD.body_json IS NOT NEW.body_json
 OR OLD.body_hash IS NOT NEW.body_hash OR OLD.proposal_event_id IS NOT NEW.proposal_event_id
BEGIN SELECT RAISE(ABORT, 'candidate body is immutable'); END;
CREATE TRIGGER policy_candidates_state_transition BEFORE UPDATE ON policy_candidates
WHEN NOT ((OLD.current_status='PROPOSED' AND NEW.current_status IN ('APPROVED','REJECTED'))
       OR (OLD.current_status='APPROVED' AND NEW.current_status IN ('SCHEDULED','REJECTED'))
       OR (OLD.current_status='SCHEDULED' AND NEW.current_status='ROLLED_BACK'))
BEGIN SELECT RAISE(ABORT, 'invalid candidate state transition'); END;
CREATE TRIGGER policy_candidates_immutable_delete BEFORE DELETE ON policy_candidates
BEGIN SELECT RAISE(ABORT, 'candidates are immutable'); END;
CREATE TRIGGER candidate_events_immutable_update BEFORE UPDATE ON candidate_events
BEGIN SELECT RAISE(ABORT, 'candidate events are immutable'); END;
CREATE TRIGGER candidate_events_immutable_delete BEFORE DELETE ON candidate_events
BEGIN SELECT RAISE(ABORT, 'candidate events are immutable'); END;
CREATE TRIGGER measurement_idempotency_immutable_update BEFORE UPDATE ON measurement_idempotency
BEGIN SELECT RAISE(ABORT, 'measurement idempotency is immutable'); END;
CREATE TRIGGER measurement_idempotency_immutable_delete BEFORE DELETE ON measurement_idempotency
BEGIN SELECT RAISE(ABORT, 'measurement idempotency is immutable'); END;
