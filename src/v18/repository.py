from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Final, final

from pydantic import TypeAdapter

from src.v17.database import Connection, SqlValue, configure, connect

from .canonical import JsonValue, canonical_hash, canonical_json, content_hash, model_json
from .errors import FaultInjected, V18Error
from .migrations import migrate_database, validate_schema
from .models import PredictionRecord
from .predictions import prediction_semantic_key, validate_prediction_record
from .quarantine import StoredQuarantine
from .reconciliation import reconcile
from .schema import GENESIS_HASH, MEASUREMENT_EVENT_SCHEMA_VERSION, MEASUREMENT_TABLES

_PREDICTION: Final = TypeAdapter(PredictionRecord)


@dataclass(frozen=True, slots=True)
class StoredPrediction:
    record: PredictionRecord
    duplicate: bool
    event_id: str


def hit(fault: str | None, checkpoint: str) -> None:
    if fault == checkpoint:
        raise FaultInjected(checkpoint)


@final
class MeasurementRepository:
    def __init__(self, path: Path, connection: Connection) -> None:
        self.path = path
        self.connection = connection
        self._closed = False

    @classmethod
    def open(cls, path: Path, *, migrate: bool = False) -> MeasurementRepository:
        if migrate:
            _ = migrate_database(path)
        if not path.is_file():
            raise V18Error("DATABASE_NOT_FOUND", str(path))
        connection = connect(path)
        try:
            configure(connection, writable=True)
            _ = validate_schema(connection)
            reconcile(connection)
        except BaseException:  # noqa: BROAD_EXCEPT_OK - resource cleanup then re-raise.
            connection.close()
            raise
        return cls(path, connection)

    def __enter__(self) -> MeasurementRepository:
        return self

    def __exit__(
        self,
        _kind: type[BaseException] | None,
        _value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if not self._closed:
            self.connection.close()
            self._closed = True

    def begin(self) -> None:
        if self._closed:
            raise V18Error("STORE_CLOSED", str(self.path))
        _ = self.connection.execute("BEGIN IMMEDIATE")
        try:
            reconcile(self.connection)
        except BaseException:  # noqa: BROAD_EXCEPT_OK - failed reconciliation rolls back the transaction.
            self.connection.rollback()
            raise

    def reconcile(self) -> None:
        reconcile(self.connection)

    def append_event(
        self, event_type: str, aggregate_id: str, semantic_key: str,
        payload: JsonValue, created_as_of: str,
    ) -> str:
        row = self.connection.execute(
            "SELECT event_hash FROM measurement_events ORDER BY sequence DESC LIMIT 1"
        ).fetchone()
        match row:  # noqa: MATCH_OK - SQLite event head is runtime-shaped.
            case None:
                previous = GENESIS_HASH
            case (str(digest),):
                previous = digest
            case _:
                raise V18Error("DATABASE_ROW_INVALID", "measurement event head")
        event_body: JsonValue = {
            "aggregate_id": aggregate_id,
            "created_as_of": created_as_of,
            "event_schema_version": MEASUREMENT_EVENT_SCHEMA_VERSION,
            "event_type": event_type,
            "payload": payload,
            "previous_event_hash": previous,
            "semantic_key": semantic_key,
        }
        event_id = canonical_hash({"event": event_body, "kind": "event-id"})
        event_hash = canonical_hash({"event": event_body, "event_id": event_id})
        _ = self.connection.execute(
            "INSERT INTO measurement_events(event_id,event_schema_version,event_type,aggregate_id,"
            + "semantic_key,payload_json,previous_event_hash,event_hash,created_as_of) "
            + "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                event_id, MEASUREMENT_EVENT_SCHEMA_VERSION, event_type, aggregate_id,
                semantic_key, canonical_json(payload).decode("utf-8"), previous,
                event_hash, created_as_of,
            ),
        )
        return event_id

    def register_prediction(
        self, record: PredictionRecord, *, fault: str | None = None,
    ) -> StoredPrediction:
        validate_prediction_record(record)
        semantic = prediction_semantic_key(record)
        body = model_json(record)
        body_hash = canonical_hash(body)
        self.begin()
        try:
            duplicate = self.stored_result("register_prediction", semantic, body_hash)
            if duplicate is not None:
                stored = self.get_prediction(record.prediction_id)
                self.connection.commit()
                return StoredPrediction(stored, True, duplicate)
            conflict = self.connection.execute(
                "SELECT body_hash FROM predictions WHERE recommendation_id=?",
                (record.recommendation_id,),
            ).fetchone()
            if conflict is not None:
                raise V18Error("PREDICTION_IDENTITY_CONFLICT", record.recommendation_id)
            payload: JsonValue = {"prediction_id": record.prediction_id, "state": "REGISTERED"}
            event_id = self.append_event(
                "prediction.registered", record.prediction_id, semantic, payload,
                record.recorded_as_of,
            )
            hit(fault, "after_event_append")
            self._insert_prediction(record, body, body_hash, event_id)
            hit(fault, "after_immutable_row_insert")
            self.store_result("register_prediction", semantic, body_hash, payload, event_id)
            hit(fault, "after_idempotency_insert")
            if canonical_hash(model_json(self.get_prediction(record.prediction_id))) != body_hash:
                raise V18Error("PREDICTION_HASH_MISMATCH", record.prediction_id)
            hit(fault, "after_final_invariant")
            self.reconcile()
            self.connection.commit()
            return StoredPrediction(record, False, event_id)
        except BaseException:  # noqa: BROAD_EXCEPT_OK - transaction rollback then re-raise.
            self.connection.rollback()
            raise

    def _insert_prediction(
        self, record: PredictionRecord, body: JsonValue, body_hash: str, event_id: str,
    ) -> None:
        values: tuple[SqlValue, ...] = (
            record.prediction_id, record.recommendation_id, record.namespace.market.value,
            record.namespace.currency.value, record.namespace.account_id, record.namespace.arm_id,
            record.namespace.symbol, record.prediction_session, record.horizon_sessions,
            record.action.value, record.reference_price_minor, record.lineage.runtime_identity,
            record.lineage.config_version, record.lineage.source_policy_version,
            record.lineage.calendar_version, record.lineage.calendar_hash,
            record.lineage.price_adjustment_version,
            canonical_json(
                {key: value for key, value in record.perspective_scores.items()}
            ).decode("utf-8"),
            record.perspective_scores_as_of, record.source_payload_hash, record.recorded_as_of,
            canonical_json(body).decode("utf-8"), body_hash, "REGISTERED", event_id,
        )
        _ = self.connection.execute(
            "INSERT INTO predictions(prediction_id,recommendation_id,market,currency,account_id,"
            + "arm_id,symbol,prediction_session,horizon_sessions,action,reference_price_minor,"
            + "runtime_identity,config_version,source_policy_version,calendar_version,calendar_hash,"
            + "price_adjustment_version,perspective_scores_json,perspective_scores_as_of,"
            + "source_payload_hash,recorded_as_of,body_json,body_hash,current_state,registration_event_id) "
            + "VALUES(" + ",".join("?" for _ in values) + ")",
            values,
        )

    def quarantine_legacy(
        self, source: bytes, source_label: str, observed_schema_hint: str,
        rejection_codes: tuple[str, ...], observed_as_of: str,
        *, fault: str | None = None,
    ) -> StoredQuarantine:
        from .quarantine import store_quarantine

        return store_quarantine(
            self, source, source_label, observed_schema_hint,
            rejection_codes, observed_as_of, fault=fault,
        )

    def stored_result(self, command: str, semantic: str, request_hash: str) -> str | None:
        row = self.connection.execute(
            "SELECT request_hash,event_id FROM measurement_idempotency "
            + "WHERE command_type=? AND semantic_key=?",
            (command, semantic),
        ).fetchone()
        match row:  # noqa: MATCH_OK - SQLite idempotency rows are runtime-shaped.
            case None:
                return None
            case (str(stored_hash), str(event_id)) if stored_hash == request_hash:
                return event_id
            case (str(), str()):
                raise V18Error("PREDICTION_IDENTITY_CONFLICT", semantic)
            case _:
                raise V18Error("DATABASE_ROW_INVALID", "measurement idempotency")

    def store_result(
        self, command: str, semantic: str, request_hash: str,
        result: JsonValue, event_id: str,
    ) -> None:
        result_json = canonical_json(result).decode("utf-8")
        _ = self.connection.execute(
            "INSERT INTO measurement_idempotency VALUES(?,?,?,?,?,?)",
            (command, semantic, request_hash, result_json, canonical_hash(result), event_id),
        )

    def get_prediction(self, prediction_id: str) -> PredictionRecord:
        row = self.connection.execute(
            "SELECT body_json,current_state FROM predictions WHERE prediction_id=?",
            (prediction_id,),
        ).fetchone()
        match row:  # noqa: MATCH_OK - SQLite prediction rows are runtime-shaped.
            case (str(body), str(state)):
                record = _PREDICTION.validate_json(body)
                return record.model_copy(update={"current_state": state})
            case None:
                quarantine = self.connection.execute(
                    "SELECT 1 FROM legacy_prediction_quarantine WHERE quarantine_id=?",
                    (prediction_id,),
                ).fetchone()
                if quarantine is not None:
                    raise V18Error("INELIGIBLE_QUARANTINE_RECORD", prediction_id)
                raise V18Error("PREDICTION_NOT_FOUND", prediction_id)
            case _:
                raise V18Error("DATABASE_ROW_INVALID", "prediction")

    def table_hashes(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for table in MEASUREMENT_TABLES:
            rows = self.connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
            values: list[JsonValue] = []
            for row in rows:
                converted: list[JsonValue] = []
                for value in row:
                    match value:  # noqa: MATCH_OK - SqlValue union is fully handled.
                        case str() | int() | float() | None:
                            converted.append(value)
                        case bytes():
                            converted.append(content_hash(value))
                values.append(converted)
            result[table] = canonical_hash(values)
        return result
