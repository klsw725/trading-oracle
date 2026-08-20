CREATE TABLE schema_migrations (
 version INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, sha256 TEXT NOT NULL UNIQUE
);
CREATE TABLE accounts (
 account_id TEXT NOT NULL, market TEXT NOT NULL, currency TEXT NOT NULL, arm_id TEXT NOT NULL,
 mode TEXT NOT NULL CHECK (mode='paper'), opening_cash_minor INTEGER NOT NULL CHECK (opening_cash_minor>=0),
 runtime_identity TEXT NOT NULL, config_version TEXT NOT NULL, policy_version TEXT NOT NULL,
 head_sequence INTEGER, head_event_hash TEXT,
 PRIMARY KEY (account_id,market,currency,arm_id),
 CHECK ((market='KR' AND currency='KRW') OR (market='US' AND currency='USD')),
 CHECK ((head_sequence IS NULL)=(head_event_hash IS NULL)),
 FOREIGN KEY (account_id,market,currency,arm_id,head_sequence,head_event_hash)
  REFERENCES events(account_id,market,currency,arm_id,sequence,event_hash)
  DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE events (
 account_id TEXT NOT NULL, market TEXT NOT NULL, currency TEXT NOT NULL, arm_id TEXT NOT NULL,
 sequence INTEGER NOT NULL, event_schema_version TEXT NOT NULL, event_id TEXT NOT NULL,
 event_type TEXT NOT NULL, semantic_key TEXT NOT NULL UNIQUE, runtime_identity TEXT NOT NULL,
 config_version TEXT NOT NULL, policy_version TEXT NOT NULL, effective_at TEXT NOT NULL,
 payload_json TEXT NOT NULL, previous_event_hash TEXT NOT NULL, event_hash TEXT NOT NULL UNIQUE,
 PRIMARY KEY (account_id,market,currency,arm_id,sequence),
 UNIQUE (account_id,market,currency,arm_id,event_id),
 UNIQUE (account_id,market,currency,arm_id,sequence,event_hash),
 UNIQUE (account_id,market,currency,arm_id,sequence,event_hash,event_id),
 FOREIGN KEY (account_id,market,currency,arm_id)
  REFERENCES accounts(account_id,market,currency,arm_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE idempotency_keys (
 account_id TEXT NOT NULL, market TEXT NOT NULL, currency TEXT NOT NULL, arm_id TEXT NOT NULL,
 command_type TEXT NOT NULL, command_id TEXT NOT NULL, config_version TEXT NOT NULL, policy_version TEXT NOT NULL,
 semantic_key TEXT NOT NULL UNIQUE, request_hash TEXT NOT NULL,
 event_sequence INTEGER NOT NULL, event_hash TEXT NOT NULL, event_id TEXT NOT NULL,
 result_json TEXT NOT NULL, result_hash TEXT NOT NULL,
 PRIMARY KEY (account_id,market,currency,arm_id,command_type,command_id,config_version,policy_version),
 UNIQUE (account_id,arm_id,command_type,command_id,config_version,policy_version),
 FOREIGN KEY (account_id,market,currency,arm_id)
  REFERENCES accounts(account_id,market,currency,arm_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY (account_id,market,currency,arm_id,event_sequence,event_hash,event_id)
  REFERENCES events(account_id,market,currency,arm_id,sequence,event_hash,event_id)
  DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE account_balances (
 account_id TEXT NOT NULL, market TEXT NOT NULL, currency TEXT NOT NULL, arm_id TEXT NOT NULL,
 available_cash_minor INTEGER NOT NULL CHECK (available_cash_minor>=0),
 reserved_cash_minor INTEGER NOT NULL CHECK (reserved_cash_minor>=0),
 PRIMARY KEY (account_id,market,currency,arm_id),
 FOREIGN KEY (account_id,market,currency,arm_id)
  REFERENCES accounts(account_id,market,currency,arm_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE account_positions (
 account_id TEXT NOT NULL, market TEXT NOT NULL, currency TEXT NOT NULL, arm_id TEXT NOT NULL,
 symbol TEXT NOT NULL, quantity INTEGER NOT NULL CHECK (quantity>0),
 average_cost_minor INTEGER NOT NULL CHECK (average_cost_minor>0),
 PRIMARY KEY (account_id,market,currency,arm_id,symbol),
 FOREIGN KEY (account_id,market,currency,arm_id)
  REFERENCES accounts(account_id,market,currency,arm_id) DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE account_reservations (
 account_id TEXT NOT NULL, market TEXT NOT NULL, currency TEXT NOT NULL, arm_id TEXT NOT NULL,
 reservation_id TEXT NOT NULL, amount_minor INTEGER NOT NULL CHECK (amount_minor>0),
 status TEXT NOT NULL CHECK (status IN ('ACTIVE','RELEASED')),
 created_event_sequence INTEGER NOT NULL, created_event_hash TEXT NOT NULL, created_event_id TEXT NOT NULL,
 released_event_sequence INTEGER, released_event_hash TEXT, released_event_id TEXT,
 PRIMARY KEY (account_id,market,currency,arm_id,reservation_id),
 CHECK ((status='ACTIVE' AND released_event_sequence IS NULL AND released_event_hash IS NULL AND released_event_id IS NULL)
     OR (status='RELEASED' AND released_event_sequence IS NOT NULL AND released_event_hash IS NOT NULL AND released_event_id IS NOT NULL)),
 FOREIGN KEY (account_id,market,currency,arm_id)
  REFERENCES accounts(account_id,market,currency,arm_id) DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY (account_id,market,currency,arm_id,created_event_sequence,created_event_hash,created_event_id)
  REFERENCES events(account_id,market,currency,arm_id,sequence,event_hash,event_id)
  DEFERRABLE INITIALLY DEFERRED,
 FOREIGN KEY (account_id,market,currency,arm_id,released_event_sequence,released_event_hash,released_event_id)
  REFERENCES events(account_id,market,currency,arm_id,sequence,event_hash,event_id)
  DEFERRABLE INITIALLY DEFERRED
);
CREATE TABLE projection_checkpoints (
 account_id TEXT NOT NULL, market TEXT NOT NULL, currency TEXT NOT NULL, arm_id TEXT NOT NULL,
 sequence INTEGER NOT NULL, event_hash TEXT NOT NULL,
 PRIMARY KEY (account_id,market,currency,arm_id),
 FOREIGN KEY (account_id,market,currency,arm_id,sequence,event_hash)
  REFERENCES events(account_id,market,currency,arm_id,sequence,event_hash)
  DEFERRABLE INITIALLY DEFERRED
);
CREATE TRIGGER events_immutable_update BEFORE UPDATE ON events
BEGIN SELECT RAISE(ABORT, 'events are immutable'); END;
CREATE TRIGGER events_immutable_delete BEFORE DELETE ON events
BEGIN SELECT RAISE(ABORT, 'events are immutable'); END;
