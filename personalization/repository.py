"""SQLite-compatible state store for personalised research daily operations."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any, Iterator, Literal, Sequence
from zoneinfo import ZoneInfo

import main

from personalization.models import ResearchProfileInput, ScheduleInput, UserInput


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _timestamp(value: datetime | None = None) -> str:
    return (value or _utc_now()).astimezone(UTC).replace(microsecond=0).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _load_list(value: str) -> tuple[str, ...]:
    raw = json.loads(value)
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError("stored JSON list is invalid")
    return tuple(raw)


def _to_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def compute_next_run(schedule: ScheduleInput, now_utc: datetime) -> datetime:
    """Return the next future UTC runtime for a user-local schedule."""

    timezone = ZoneInfo(schedule.timezone)
    local_now = now_utc.astimezone(timezone)
    candidate_date = local_now.date()
    candidate = datetime.combine(candidate_date, schedule.local_send_time, timezone)
    if candidate <= local_now:
        candidate_date += timedelta(days=1)

    if schedule.frequency == "weekdays":
        while candidate_date.weekday() > 4:
            candidate_date += timedelta(days=1)
    elif schedule.frequency == "weekly":
        assert schedule.weekday is not None
        while candidate_date.weekday() != schedule.weekday:
            candidate_date += timedelta(days=1)

    return datetime.combine(candidate_date, schedule.local_send_time, timezone).astimezone(UTC)


@dataclass(frozen=True)
class StoredResearchProfile:
    id: str
    user_id: str
    version: int
    is_current: bool
    input: ResearchProfileInput

    @property
    def include_keywords(self) -> tuple[str, ...]:
        return self.input.include_keywords


@dataclass(frozen=True)
class DueSchedule:
    schedule_id: str
    user_id: str
    profile_version: int
    report_date: date
    due_at: datetime


@dataclass(frozen=True)
class DeliveryClaim:
    delivery_id: str
    report_run_id: str
    user_id: str
    profile_version: int
    report_date: date
    mode: Literal["automatic", "manual"]
    status: str
    attempt_count: int
    created: bool


@dataclass(frozen=True)
class DeliveryRecord:
    id: str
    report_run_id: str
    user_id: str
    profile_version: int
    report_date: date
    mode: str
    status: str
    attempt_count: int
    artifact_name: str
    artifact_run_id: str
    last_error: str


@dataclass(frozen=True)
class DeliveryExecutionContext:
    claim: DeliveryClaim
    email: str
    profile: StoredResearchProfile


@dataclass(frozen=True)
class UserRecord:
    id: str
    display_name: str
    email: str
    status: str
    research_topic: str
    base_profile: str
    next_run_at: datetime | None
    timezone: str
    schedule_enabled: bool


@dataclass(frozen=True)
class ScheduleRecord:
    id: str
    user_id: str
    frequency: str
    weekday: int | None
    timezone: str
    local_send_time: str
    enabled: bool
    next_run_at: datetime | None


class PersonalizationRepository:
    """A small repository that works with sqlite3 and the libsql DB-API surface."""

    def __init__(self, connection: Any, *, is_local_replica: bool = False) -> None:
        self.connection = connection
        self.is_local_replica = is_local_replica
        self.is_local_data_ready = not is_local_replica
        self._local_schema_known_missing = False
        self.last_sync_at: datetime | None = None
        self.last_sync_error: str | None = None
        self._connection_lock = RLock()

    @classmethod
    def for_sqlite(cls, path: Path) -> "PersonalizationRepository":
        connection = sqlite3.connect(path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return cls(connection)

    @classmethod
    def for_local_replica(
        cls, path: Path, sync_url: str, auth_token: str
    ) -> "PersonalizationRepository":
        """Open a local libsql replica that is refreshed only by ``sync`` calls."""

        import libsql

        connection = libsql.connect(
            database=str(path),
            sync_url=sync_url,
            auth_token=auth_token,
            _check_same_thread=False,
        )
        repository = cls(connection, is_local_replica=True)
        repository._refresh_local_data_ready()
        return repository

    @classmethod
    def from_environment(cls) -> "PersonalizationRepository":
        url = os.environ.get("TURSO_DATABASE_URL", "").strip()
        token = os.environ.get("TURSO_AUTH_TOKEN", "").strip()
        if not url or not token:
            raise RuntimeError("TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are required")
        import libsql

        return cls(libsql.connect(database=url, auth_token=token))

    def initialize(self) -> None:
        schema = (Path(__file__).with_name("schema.sql")).read_text(encoding="utf-8")
        with self._connection_lock:
            if isinstance(self.connection, sqlite3.Connection):
                self.connection.executescript(schema)
                self.connection.commit()
                return
            for statement in schema.split(";"):
                if statement.strip() and not statement.lstrip().upper().startswith("PRAGMA"):
                    self.connection.execute(statement)
            self.connection.commit()
            self.is_local_data_ready = True

    def close(self) -> None:
        with self._connection_lock:
            self.connection.close()

    def _refresh_local_data_ready(self) -> bool:
        """Report whether the local replica has the existing application schema."""

        if not self.is_local_replica:
            self.is_local_data_ready = True
            return True
        with self._connection_lock:
            try:
                cursor = self.connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'users'"
                )
                self.is_local_data_ready = cursor.fetchone() is not None
                self._local_schema_known_missing = not self.is_local_data_ready
            except Exception:
                self.is_local_data_ready = False
                self._local_schema_known_missing = False
        return self.is_local_data_ready

    def sync(self) -> bool:
        """Pull current Turso primary data into an embedded local read replica."""

        if not self.is_local_replica:
            return False
        with self._connection_lock:
            try:
                self.connection.sync()
            except Exception as exc:
                self.last_sync_error = type(exc).__name__
                raise
            self._refresh_local_data_ready()
            if self._local_schema_known_missing:
                # The production runner normally creates this schema before the dashboard opens.
                # Keep an empty first deployment recoverable after the administrator explicitly
                # requests sync, without issuing DDL during normal page navigation.
                self.initialize()
                self.connection.sync()
                self._refresh_local_data_ready()
            self.last_sync_at = _utc_now()
            self.last_sync_error = None
        return True

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._connection_lock:
            try:
                begin_statement = "BEGIN IMMEDIATE" if isinstance(self.connection, sqlite3.Connection) else "BEGIN"
                self.connection.execute(begin_statement)
                yield
                self.connection.commit()
            except Exception:
                self.connection.rollback()
                raise

    def _execute(self, statement: str, parameters: Sequence[Any] = ()) -> Any:
        with self._connection_lock:
            return self.connection.execute(statement, tuple(parameters))

    @staticmethod
    def _normalise_row(cursor: Any, row: Any | None) -> Any | None:
        if row is None or isinstance(row, sqlite3.Row) or isinstance(row, dict):
            return row
        description = getattr(cursor, "description", None)
        if not description:
            return row
        return {
            str(column[0]): value
            for column, value in zip(description, row, strict=True)
        }

    def _fetchone(self, statement: str, parameters: Sequence[Any] = ()) -> Any | None:
        with self._connection_lock:
            cursor = self.connection.execute(statement, tuple(parameters))
            return self._normalise_row(cursor, cursor.fetchone())

    def _fetchall(self, statement: str, parameters: Sequence[Any] = ()) -> list[Any]:
        with self._connection_lock:
            cursor = self.connection.execute(statement, tuple(parameters))
            return [self._normalise_row(cursor, row) for row in cursor.fetchall()]

    @staticmethod
    def _value(row: Any, key: str) -> Any:
        if isinstance(row, sqlite3.Row):
            return row[key]
        try:
            return row[key]
        except (KeyError, TypeError, IndexError):
            return getattr(row, key)

    def _profile_from_row(self, row: Any) -> StoredResearchProfile:
        input_profile = ResearchProfileInput.from_form(
            base_profile=self._value(row, "base_profile"),
            research_topic=self._value(row, "research_topic"),
            include_keywords=_load_list(self._value(row, "include_keywords_json")),
            exclude_keywords=_load_list(self._value(row, "exclude_keywords_json")),
            source_ids=_load_list(self._value(row, "source_ids_json")),
            journal_ids=_load_list(self._value(row, "journal_ids_json")),
            content_preferences=_load_list(self._value(row, "content_preferences_json")),
            max_items=int(self._value(row, "max_items")),
            llm_provider=self._value(row, "llm_provider"),
            llm_model=self._value(row, "llm_model"),
            output_formats=_load_list(self._value(row, "output_formats_json")),
        )
        return StoredResearchProfile(
            id=self._value(row, "id"),
            user_id=self._value(row, "user_id"),
            version=int(self._value(row, "version")),
            is_current=bool(self._value(row, "is_current")),
            input=input_profile,
        )

    def _insert_profile(self, user_id: str, version: int, profile: ResearchProfileInput) -> str:
        profile_id = _new_id("prof")
        self._execute(
            """
            INSERT INTO research_profiles (
                id, user_id, version, is_current, base_profile, research_topic,
                include_keywords_json, exclude_keywords_json, source_ids_json,
                journal_ids_json, content_preferences_json, max_items, llm_provider,
                llm_model, output_formats_json, created_at
            ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                profile_id,
                user_id,
                version,
                profile.base_profile,
                profile.research_topic,
                json.dumps(profile.include_keywords),
                json.dumps(profile.exclude_keywords),
                json.dumps(profile.source_ids),
                json.dumps(profile.journal_ids),
                json.dumps(profile.content_preferences),
                profile.max_items,
                profile.llm_provider,
                profile.llm_model,
                json.dumps(profile.output_formats),
                _timestamp(),
            ),
        )
        return profile_id

    def create_user_with_profile(
        self, user: UserInput, profile: ResearchProfileInput, schedule: ScheduleInput
    ) -> str:
        user_id = _new_id("usr")
        now = _utc_now()
        with self._transaction():
            self._execute(
                "INSERT INTO users (id, display_name, email, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, user.display_name, user.email, user.status, _timestamp(now), _timestamp(now)),
            )
            self._insert_profile(user_id, 1, profile)
            self._execute(
                """
                INSERT INTO schedules (id, user_id, frequency, weekday, timezone, local_send_time, next_run_at, enabled, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _new_id("sch"),
                    user_id,
                    schedule.frequency,
                    schedule.weekday,
                    schedule.timezone,
                    schedule.local_send_time.strftime("%H:%M"),
                    _timestamp(compute_next_run(schedule, now)),
                    int(schedule.enabled),
                    _timestamp(now),
                ),
            )
        return user_id

    def save_profile_version(self, user_id: str, profile: ResearchProfileInput) -> int:
        with self._transaction():
            row = self._fetchone(
                "SELECT COALESCE(MAX(version), 0) AS version FROM research_profiles WHERE user_id = ?",
                (user_id,),
            )
            if row is None:
                raise ValueError("user does not have a profile")
            next_version = int(self._value(row, "version")) + 1
            self._execute(
                "UPDATE research_profiles SET is_current = 0 WHERE user_id = ? AND is_current = 1",
                (user_id,),
            )
            self._insert_profile(user_id, next_version, profile)
            self._execute(
                "UPDATE users SET updated_at = ? WHERE id = ?", (_timestamp(), user_id)
            )
        return next_version

    def get_current_profile(self, user_id: str) -> StoredResearchProfile:
        row = self._fetchone(
            "SELECT * FROM research_profiles WHERE user_id = ? AND is_current = 1", (user_id,)
        )
        if row is None:
            raise ValueError("user does not have a current profile")
        return self._profile_from_row(row)

    def list_profile_versions(self, user_id: str) -> list[StoredResearchProfile]:
        rows = self._fetchall(
            "SELECT * FROM research_profiles WHERE user_id = ? ORDER BY version ASC", (user_id,)
        )
        return [self._profile_from_row(row) for row in rows]

    def get_schedule(self, user_id: str) -> ScheduleRecord:
        row = self._fetchone("SELECT * FROM schedules WHERE user_id = ?", (user_id,))
        if row is None:
            raise ValueError("user does not have a schedule")
        next_run_at = self._value(row, "next_run_at")
        weekday = self._value(row, "weekday")
        return ScheduleRecord(
            id=self._value(row, "id"),
            user_id=self._value(row, "user_id"),
            frequency=self._value(row, "frequency"),
            weekday=int(weekday) if weekday is not None else None,
            timezone=self._value(row, "timezone"),
            local_send_time=self._value(row, "local_send_time"),
            enabled=bool(self._value(row, "enabled")),
            next_run_at=_to_datetime(next_run_at) if next_run_at else None,
        )

    def update_schedule(self, user_id: str, schedule: ScheduleInput) -> None:
        current = self.get_schedule(user_id)
        now = _utc_now()
        with self._transaction():
            self._execute(
                """
                UPDATE schedules
                SET frequency = ?, weekday = ?, timezone = ?, local_send_time = ?,
                    next_run_at = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    schedule.frequency,
                    schedule.weekday,
                    schedule.timezone,
                    schedule.local_send_time.strftime("%H:%M"),
                    _timestamp(compute_next_run(schedule, now)),
                    int(schedule.enabled),
                    _timestamp(now),
                    current.id,
                ),
            )

    def activate_schedule_after_preview(
        self, user_id: str, delivery_id: str, now_utc: datetime
    ) -> ScheduleRecord:
        """Enable a user's saved schedule after that user approves a ready manual preview."""

        with self._transaction():
            row = self._fetchone(
                """
                SELECT schedules.*, deliveries.report_run_id
                FROM deliveries
                JOIN schedules ON schedules.user_id = deliveries.user_id
                WHERE deliveries.id = ?
                  AND deliveries.user_id = ?
                  AND deliveries.mode = 'manual'
                  AND deliveries.status = 'preview_ready'
                """,
                (delivery_id, user_id),
            )
            if row is None:
                raise ValueError("delivery must be this user's manual preview_ready preview")
            schedule = ScheduleInput.from_form(
                frequency=self._value(row, "frequency"),
                weekday=self._value(row, "weekday"),
                timezone=self._value(row, "timezone"),
                local_send_time=self._value(row, "local_send_time"),
                enabled=True,
            )
            next_run_at = compute_next_run(schedule, now_utc)
            self._execute(
                """
                UPDATE schedules
                SET enabled = 1, next_run_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (_timestamp(next_run_at), _timestamp(now_utc), self._value(row, "id")),
            )
            self._append_event(
                self._value(row, "report_run_id"),
                delivery_id,
                "schedule_activated",
                "Schedule activated after preview approval",
            )
            return ScheduleRecord(
                id=self._value(row, "id"),
                user_id=user_id,
                frequency=schedule.frequency,
                weekday=schedule.weekday,
                timezone=schedule.timezone,
                local_send_time=schedule.local_send_time.strftime("%H:%M"),
                enabled=True,
                next_run_at=next_run_at,
            )

    def list_users(self) -> list[UserRecord]:
        rows = self._fetchall(
            """
            SELECT users.id, users.display_name, users.email, users.status,
                   research_profiles.research_topic, research_profiles.base_profile,
                   schedules.next_run_at, schedules.timezone, schedules.enabled
            FROM users
            JOIN research_profiles ON research_profiles.user_id = users.id AND research_profiles.is_current = 1
            JOIN schedules ON schedules.user_id = users.id
            ORDER BY users.created_at DESC
            """
        )
        return [
            UserRecord(
                id=self._value(row, "id"),
                display_name=self._value(row, "display_name"),
                email=self._value(row, "email"),
                status=self._value(row, "status"),
                research_topic=self._value(row, "research_topic"),
                base_profile=self._value(row, "base_profile"),
                next_run_at=_to_datetime(self._value(row, "next_run_at"))
                if self._value(row, "next_run_at")
                else None,
                timezone=self._value(row, "timezone"),
                schedule_enabled=bool(self._value(row, "enabled")),
            )
            for row in rows
        ]

    def set_user_status(self, user_id: str, status: Literal["active", "paused", "expired"]) -> None:
        if status not in {"active", "paused", "expired"}:
            raise ValueError("invalid user status")
        with self._transaction():
            self._execute(
                "UPDATE users SET status = ?, updated_at = ? WHERE id = ?",
                (status, _timestamp(), user_id),
            )
            self._execute(
                "UPDATE schedules SET enabled = ?, updated_at = ? WHERE user_id = ?",
                (int(status == "active"), _timestamp(), user_id),
            )

    def operations_snapshot(self) -> dict[str, int]:
        user_count = self._fetchone("SELECT COUNT(*) AS count FROM users")
        delivery_counts = self._fetchone(
            """
            SELECT
                SUM(CASE WHEN status IN ('queued', 'claimed', 'sending') THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN status = 'sent' THEN 1 ELSE 0 END) AS sent,
                SUM(CASE WHEN status = 'retryable_failed' THEN 1 ELSE 0 END) AS retryable_failed
            FROM deliveries
            """
        )
        return {
            "total_users": int(self._value(user_count, "count")) if user_count else 0,
            "pending": int(self._value(delivery_counts, "pending") or 0) if delivery_counts else 0,
            "sent": int(self._value(delivery_counts, "sent") or 0) if delivery_counts else 0,
            "retryable_failed": int(self._value(delivery_counts, "retryable_failed") or 0)
            if delivery_counts
            else 0,
        }

    def list_recent_deliveries(self, limit: int = 30) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT deliveries.*, users.display_name, schedules.enabled AS schedule_enabled
            FROM deliveries
            JOIN users ON users.id = deliveries.user_id
            JOIN schedules ON schedules.user_id = deliveries.user_id
            ORDER BY deliveries.updated_at DESC LIMIT ?
            """,
            (limit,),
        )
        return [
            {
                "id": self._value(row, "id"),
                "user_id": self._value(row, "user_id"),
                "display_name": self._value(row, "display_name"),
                "report_date": self._value(row, "report_date"),
                "mode": self._value(row, "mode"),
                "status": self._value(row, "status"),
                "schedule_enabled": bool(self._value(row, "schedule_enabled")),
                "artifact_name": self._value(row, "artifact_name"),
                "artifact_run_id": self._value(row, "artifact_run_id"),
                "last_error": self._value(row, "last_error"),
                "updated_at": self._value(row, "updated_at"),
            }
            for row in rows
        ]

    def list_recent_events(self, limit: int = 40) -> list[dict[str, str]]:
        rows = self._fetchall(
            """
            SELECT run_events.event_type, run_events.message, run_events.created_at,
                   users.display_name
            FROM run_events
            JOIN report_runs ON report_runs.id = run_events.report_run_id
            JOIN users ON users.id = report_runs.user_id
            ORDER BY run_events.created_at DESC LIMIT ?
            """,
            (limit,),
        )
        return [
            {
                "display_name": self._value(row, "display_name"),
                "event_type": self._value(row, "event_type"),
                "message": self._value(row, "message"),
                "created_at": self._value(row, "created_at"),
            }
            for row in rows
        ]

    def list_source_metrics(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._fetchall(
            """
            SELECT source_name, success, item_count, error_summary, duration_ms, created_at
            FROM source_metrics ORDER BY created_at DESC LIMIT ?
            """,
            (limit,),
        )
        return [
            {
                "source_name": self._value(row, "source_name"),
                "success": bool(self._value(row, "success")),
                "item_count": int(self._value(row, "item_count")),
                "error_summary": self._value(row, "error_summary"),
                "duration_ms": int(self._value(row, "duration_ms")),
                "created_at": self._value(row, "created_at"),
            }
            for row in rows
        ]

    def make_due_schedule(self, user_id: str, local_date: date, due_at: datetime) -> DueSchedule:
        row = self._fetchone("SELECT id FROM schedules WHERE user_id = ?", (user_id,))
        if row is None:
            raise ValueError("user does not have a schedule")
        profile = self.get_current_profile(user_id)
        return DueSchedule(
            schedule_id=self._value(row, "id"),
            user_id=user_id,
            profile_version=profile.version,
            report_date=local_date,
            due_at=due_at.astimezone(UTC),
        )

    def list_due_schedules(self, now_utc: datetime) -> list[DueSchedule]:
        rows = self._fetchall(
            """
            SELECT schedules.id AS schedule_id, schedules.user_id, schedules.next_run_at, schedules.timezone,
                   research_profiles.version AS profile_version
            FROM schedules
            JOIN users ON users.id = schedules.user_id
            JOIN research_profiles ON research_profiles.user_id = users.id AND research_profiles.is_current = 1
            WHERE schedules.enabled = 1 AND users.status = 'active' AND schedules.next_run_at <= ?
            ORDER BY schedules.next_run_at ASC
            """,
            (_timestamp(now_utc),),
        )
        due_schedules: list[DueSchedule] = []
        for row in rows:
            due_at = _to_datetime(self._value(row, "next_run_at"))
            local_date = due_at.astimezone(ZoneInfo(self._value(row, "timezone"))).date()
            due_schedules.append(
                DueSchedule(
                    schedule_id=self._value(row, "schedule_id"),
                    user_id=self._value(row, "user_id"),
                    profile_version=int(self._value(row, "profile_version")),
                    report_date=local_date,
                    due_at=due_at,
                )
            )
        return due_schedules

    def set_schedule_next_run(self, schedule_id: str, next_run_at: datetime) -> None:
        with self._transaction():
            self._execute(
                "UPDATE schedules SET next_run_at = ?, updated_at = ? WHERE id = ?",
                (_timestamp(next_run_at), _timestamp(), schedule_id),
            )

    def advance_schedule(self, schedule_id: str, now_utc: datetime) -> None:
        row = self._fetchone("SELECT * FROM schedules WHERE id = ?", (schedule_id,))
        if row is None:
            raise ValueError("schedule does not exist")
        schedule = ScheduleInput.from_form(
            frequency=self._value(row, "frequency"),
            weekday=self._value(row, "weekday"),
            timezone=self._value(row, "timezone"),
            local_send_time=self._value(row, "local_send_time"),
            enabled=bool(self._value(row, "enabled")),
        )
        self.set_schedule_next_run(schedule_id, compute_next_run(schedule, now_utc))

    def _advance_due_schedule_in_transaction(self, due: DueSchedule) -> None:
        row = self._fetchone("SELECT * FROM schedules WHERE id = ?", (due.schedule_id,))
        if row is None:
            raise ValueError("schedule does not exist")
        next_run_at = self._value(row, "next_run_at")
        if next_run_at and _to_datetime(next_run_at) > due.due_at:
            return
        schedule = ScheduleInput.from_form(
            frequency=self._value(row, "frequency"),
            weekday=self._value(row, "weekday"),
            timezone=self._value(row, "timezone"),
            local_send_time=self._value(row, "local_send_time"),
            enabled=bool(self._value(row, "enabled")),
        )
        self._execute(
            "UPDATE schedules SET next_run_at = ?, updated_at = ? WHERE id = ?",
            (
                _timestamp(compute_next_run(schedule, due.due_at)),
                _timestamp(),
                due.schedule_id,
            ),
        )

    def _create_report_run(
        self, user_id: str, profile_version: int, report_date: date, mode: str
    ) -> str:
        run_id = _new_id("run")
        self._execute(
            """
            INSERT INTO report_runs (id, user_id, profile_version, report_date, mode, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'queued', ?)
            """,
            (run_id, user_id, profile_version, report_date.isoformat(), mode, _timestamp()),
        )
        return run_id

    def _append_event(self, report_run_id: str, delivery_id: str, event_type: str, message: str) -> None:
        self._execute(
            "INSERT INTO run_events (id, report_run_id, delivery_id, event_type, message, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (_new_id("evt"), report_run_id, delivery_id, event_type, message[:500], _timestamp()),
        )

    def _claim_from_row(self, row: Any, created: bool) -> DeliveryClaim:
        return DeliveryClaim(
            delivery_id=self._value(row, "id"),
            report_run_id=self._value(row, "report_run_id"),
            user_id=self._value(row, "user_id"),
            profile_version=int(self._value(row, "profile_version")),
            report_date=date.fromisoformat(self._value(row, "report_date")),
            mode=self._value(row, "mode"),
            status=self._value(row, "status"),
            attempt_count=int(self._value(row, "attempt_count")),
            created=created,
        )

    def enqueue_automatic_delivery(self, due: DueSchedule) -> DeliveryClaim:
        key = f"automatic:{due.user_id}:{due.report_date.isoformat()}:email"
        with self._transaction():
            run_id = self._create_report_run(
                due.user_id, due.profile_version, due.report_date, "automatic"
            )
            delivery_id = _new_id("dlv")
            self._execute(
                """
                INSERT INTO deliveries (
                    id, user_id, report_run_id, profile_version, report_date, channel, mode,
                    status, idempotency_key, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'email', 'automatic', 'queued', ?, ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (
                    delivery_id,
                    due.user_id,
                    run_id,
                    due.profile_version,
                    due.report_date.isoformat(),
                    key,
                    _timestamp(),
                    _timestamp(),
                ),
            )
            row = self._fetchone("SELECT * FROM deliveries WHERE idempotency_key = ?", (key,))
            assert row is not None
            if self._value(row, "id") != delivery_id:
                self._execute("DELETE FROM report_runs WHERE id = ?", (run_id,))
                self._advance_due_schedule_in_transaction(due)
                return self._claim_from_row(row, created=False)
            self._advance_due_schedule_in_transaction(due)
            self._append_event(run_id, delivery_id, "delivery_queued", "Automatic delivery queued")
            return self._claim_from_row(row, created=True)

    def create_manual_preview(self, user_id: str, report_date: date) -> DeliveryClaim:
        profile = self.get_current_profile(user_id)
        with self._transaction():
            run_id = self._create_report_run(user_id, profile.version, report_date, "manual")
            delivery_id = _new_id("dlv")
            key = f"manual:{run_id}:email"
            self._execute(
                """
                INSERT INTO deliveries (
                    id, user_id, report_run_id, profile_version, report_date, channel, mode,
                    status, idempotency_key, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'email', 'manual', 'queued', ?, ?, ?)
                """,
                (
                    delivery_id,
                    user_id,
                    run_id,
                    profile.version,
                    report_date.isoformat(),
                    key,
                    _timestamp(),
                    _timestamp(),
                ),
            )
            row = self._fetchone("SELECT * FROM deliveries WHERE id = ?", (delivery_id,))
            assert row is not None
            self._append_event(run_id, delivery_id, "preview_queued", "Manual preview queued")
            return self._claim_from_row(row, created=True)

    def get_delivery(self, delivery_id: str) -> DeliveryRecord:
        row = self._fetchone("SELECT * FROM deliveries WHERE id = ?", (delivery_id,))
        if row is None:
            raise ValueError("delivery does not exist")
        return DeliveryRecord(
            id=self._value(row, "id"),
            report_run_id=self._value(row, "report_run_id"),
            user_id=self._value(row, "user_id"),
            profile_version=int(self._value(row, "profile_version")),
            report_date=date.fromisoformat(self._value(row, "report_date")),
            mode=self._value(row, "mode"),
            status=self._value(row, "status"),
            attempt_count=int(self._value(row, "attempt_count")),
            artifact_name=self._value(row, "artifact_name"),
            artifact_run_id=self._value(row, "artifact_run_id"),
            last_error=self._value(row, "last_error"),
        )

    def get_delivery_execution_context(self, delivery_id: str) -> DeliveryExecutionContext:
        delivery_row = self._fetchone("SELECT * FROM deliveries WHERE id = ?", (delivery_id,))
        if delivery_row is None:
            raise ValueError("delivery does not exist")
        profile_row = self._fetchone(
            "SELECT * FROM research_profiles WHERE user_id = ? AND version = ?",
            (
                self._value(delivery_row, "user_id"),
                self._value(delivery_row, "profile_version"),
            ),
        )
        user_row = self._fetchone(
            "SELECT email FROM users WHERE id = ?", (self._value(delivery_row, "user_id"),)
        )
        if profile_row is None or user_row is None:
            raise ValueError("delivery user or profile does not exist")
        return DeliveryExecutionContext(
            claim=self._claim_from_row(delivery_row, created=False),
            email=self._value(user_row, "email"),
            profile=self._profile_from_row(profile_row),
        )

    def list_deliveries_for_user(self, user_id: str) -> list[DeliveryRecord]:
        rows = self._fetchall(
            "SELECT * FROM deliveries WHERE user_id = ? ORDER BY created_at ASC", (user_id,)
        )
        return [self.get_delivery(self._value(row, "id")) for row in rows]

    def claim_delivery(self, delivery_id: str) -> DeliveryClaim | None:
        with self._transaction():
            row = self._fetchone("SELECT * FROM deliveries WHERE id = ?", (delivery_id,))
            if row is None or self._value(row, "status") != "queued":
                return None
            self._execute(
                "UPDATE deliveries SET status = 'claimed', attempt_count = attempt_count + 1, updated_at = ? WHERE id = ?",
                (_timestamp(), delivery_id),
            )
            self._execute(
                "UPDATE report_runs SET status = 'running', started_at = ? WHERE id = ?",
                (_timestamp(), self._value(row, "report_run_id")),
            )
            updated = self._fetchone("SELECT * FROM deliveries WHERE id = ?", (delivery_id,))
            assert updated is not None
            self._append_event(
                self._value(updated, "report_run_id"), delivery_id, "delivery_claimed", "Delivery claimed"
            )
            return self._claim_from_row(updated, created=False)

    def claim_automatic_retry(self, delivery_id: str) -> DeliveryClaim | None:
        with self._transaction():
            row = self._fetchone("SELECT * FROM deliveries WHERE id = ?", (delivery_id,))
            if (
                row is None
                or self._value(row, "mode") != "automatic"
                or self._value(row, "status") != "retryable_failed"
                or int(self._value(row, "attempt_count")) >= 3
            ):
                return None
            self._execute(
                "UPDATE deliveries SET status = 'claimed', attempt_count = attempt_count + 1, updated_at = ? WHERE id = ?",
                (_timestamp(), delivery_id),
            )
            self._execute(
                "UPDATE report_runs SET status = 'running', started_at = ?, error_summary = '' WHERE id = ?",
                (_timestamp(), self._value(row, "report_run_id")),
            )
            updated = self._fetchone("SELECT * FROM deliveries WHERE id = ?", (delivery_id,))
            assert updated is not None
            self._append_event(
                self._value(updated, "report_run_id"), delivery_id, "automatic_retry_claimed", "Automatic retry claimed"
            )
            return self._claim_from_row(updated, created=False)

    def list_recoverable_automatic_delivery_ids(self) -> list[str]:
        rows = self._fetchall(
            """
            SELECT id FROM deliveries
            WHERE mode = 'automatic' AND status = 'retryable_failed' AND attempt_count < 3
            ORDER BY updated_at ASC
            """
        )
        return [self._value(row, "id") for row in rows]

    def recover_expired_deliveries(
        self, now_utc: datetime, lease_minutes: int
    ) -> list[str]:
        if lease_minutes < 1:
            raise ValueError("lease_minutes must be positive")
        cutoff = _timestamp(now_utc - timedelta(minutes=lease_minutes))
        message = "Execution lease expired before completion"
        with self._transaction():
            rows = self._fetchall(
                """
                SELECT id, report_run_id FROM deliveries
                WHERE status IN ('claimed', 'sending') AND updated_at <= ?
                ORDER BY updated_at ASC
                """,
                (cutoff,),
            )
            recovered_ids: list[str] = []
            for row in rows:
                delivery_id = self._value(row, "id")
                run_id = self._value(row, "report_run_id")
                self._execute(
                    """
                    UPDATE deliveries
                    SET status = 'retryable_failed', last_error = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (message, _timestamp(now_utc), delivery_id),
                )
                self._execute(
                    """
                    UPDATE report_runs
                    SET status = 'failed', error_summary = ?, finished_at = ?
                    WHERE id = ?
                    """,
                    (message, _timestamp(now_utc), run_id),
                )
                self._append_event(run_id, delivery_id, "delivery_lease_expired", message)
                recovered_ids.append(delivery_id)
            return recovered_ids

    def mark_preview_ready(
        self, delivery_id: str, run_id: str, artifact_name: str, github_run_id: str
    ) -> None:
        with self._transaction():
            self._execute(
                """
                UPDATE deliveries
                SET status = 'preview_ready', artifact_name = ?, artifact_run_id = ?, updated_at = ?
                WHERE id = ? AND status = 'claimed'
                """,
                (artifact_name, github_run_id, _timestamp(), delivery_id),
            )
            self._execute(
                """
                UPDATE report_runs
                SET status = 'preview_ready', artifact_name = ?, github_run_id = ?, finished_at = ?
                WHERE id = ?
                """,
                (artifact_name, github_run_id, _timestamp(), run_id),
            )
            self._append_event(run_id, delivery_id, "preview_ready", "Preview generated")

    def queue_preview_delivery(self, delivery_id: str) -> DeliveryClaim | None:
        with self._transaction():
            row = self._fetchone("SELECT * FROM deliveries WHERE id = ?", (delivery_id,))
            if row is None or self._value(row, "status") != "preview_ready":
                return None
            self._execute(
                "UPDATE deliveries SET status = 'queued', updated_at = ? WHERE id = ?",
                (_timestamp(), delivery_id),
            )
            updated = self._fetchone("SELECT * FROM deliveries WHERE id = ?", (delivery_id,))
            assert updated is not None
            self._append_event(
                self._value(updated, "report_run_id"), delivery_id, "delivery_confirmed", "Preview delivery confirmed"
            )
            return self._claim_from_row(updated, created=False)

    def claim_queued_preview_delivery(self, delivery_id: str) -> DeliveryClaim | None:
        with self._transaction():
            row = self._fetchone("SELECT * FROM deliveries WHERE id = ?", (delivery_id,))
            if row is None or self._value(row, "status") != "queued" or self._value(row, "mode") != "manual":
                return None
            self._execute(
                "UPDATE deliveries SET status = 'sending', attempt_count = attempt_count + 1, updated_at = ? WHERE id = ?",
                (_timestamp(), delivery_id),
            )
            updated = self._fetchone("SELECT * FROM deliveries WHERE id = ?", (delivery_id,))
            assert updated is not None
            self._append_event(
                self._value(updated, "report_run_id"), delivery_id, "delivery_sending", "Preview delivery sending"
            )
            return self._claim_from_row(updated, created=False)

    def mark_sent(self, delivery_id: str) -> None:
        with self._transaction():
            row = self._fetchone("SELECT * FROM deliveries WHERE id = ?", (delivery_id,))
            if row is None or self._value(row, "status") not in {"claimed", "sending"}:
                return
            self._execute(
                "UPDATE deliveries SET status = 'sent', sent_at = ?, updated_at = ?, last_error = '' WHERE id = ?",
                (_timestamp(), _timestamp(), delivery_id),
            )
            self._execute(
                "UPDATE report_runs SET status = 'completed', finished_at = ? WHERE id = ?",
                (_timestamp(), self._value(row, "report_run_id")),
            )
            self._append_event(
                self._value(row, "report_run_id"), delivery_id, "delivery_sent", "Email delivered"
            )

    def mark_retryable_failure(self, delivery_id: str, error_summary: str) -> None:
        with self._transaction():
            row = self._fetchone("SELECT * FROM deliveries WHERE id = ?", (delivery_id,))
            if row is None:
                return
            self._execute(
                "UPDATE deliveries SET status = 'retryable_failed', last_error = ?, updated_at = ? WHERE id = ?",
                (error_summary[:500], _timestamp(), delivery_id),
            )
            self._execute(
                "UPDATE report_runs SET status = 'failed', error_summary = ?, finished_at = ? WHERE id = ?",
                (error_summary[:500], _timestamp(), self._value(row, "report_run_id")),
            )
            self._append_event(
                self._value(row, "report_run_id"), delivery_id, "delivery_failed", error_summary
            )

    def retry_delivery(self, delivery_id: str) -> Literal["preview", "deliver"] | None:
        with self._transaction():
            row = self._fetchone("SELECT * FROM deliveries WHERE id = ?", (delivery_id,))
            if (
                row is None
                or self._value(row, "mode") != "manual"
                or self._value(row, "status") != "retryable_failed"
            ):
                return None
            action: Literal["preview", "deliver"] = (
                "deliver"
                if self._value(row, "artifact_name") and self._value(row, "artifact_run_id")
                else "preview"
            )
            self._execute(
                "UPDATE deliveries SET status = 'queued', updated_at = ? WHERE id = ?",
                (_timestamp(), delivery_id),
            )
            self._append_event(
                self._value(row, "report_run_id"), delivery_id, "delivery_retry_queued", f"Retry queued for {action}"
            )
            return action

    def history_for_user(
        self, user_id: str, report_date: date, lookback_days: int
    ) -> dict[str, set[str]]:
        cutoff = (report_date - timedelta(days=lookback_days)).isoformat()
        rows = self._fetchall(
            """
            SELECT identity_keys_json, title_key, topic_key FROM report_items
            WHERE user_id = ? AND report_date >= ? AND report_date < ?
            """,
            (user_id, cutoff, report_date.isoformat()),
        )
        history = {"identity_keys": set(), "title_keys": set(), "topic_keys": set()}
        for row in rows:
            history["identity_keys"].update(_load_list(self._value(row, "identity_keys_json")))
            if self._value(row, "title_key"):
                history["title_keys"].add(self._value(row, "title_key"))
            if self._value(row, "topic_key"):
                history["topic_keys"].add(self._value(row, "topic_key"))
        return history

    def record_report_items(
        self,
        run_id: str,
        user_id: str,
        report_date: date,
        profile: dict[str, Any],
        items: list[main.NewsItem],
    ) -> None:
        run_row = self._fetchone("SELECT profile_version FROM report_runs WHERE id = ?", (run_id,))
        if run_row is None:
            raise ValueError("report run does not exist")
        profile_version = int(self._value(run_row, "profile_version"))
        with self._transaction():
            self._execute("DELETE FROM report_items WHERE report_run_id = ?", (run_id,))
            for item in items:
                payload = main.history_item_payload(item, profile)
                self._execute(
                    """
                    INSERT INTO report_items (
                        id, report_run_id, user_id, report_date, profile_version, doi, link,
                        title, source, published_at, score, identity_keys_json, title_key, topic_key
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _new_id("item"),
                        run_id,
                        user_id,
                        report_date.isoformat(),
                        profile_version,
                        payload["doi"],
                        payload["link"],
                        payload["title"],
                        payload["source"],
                        payload["published"],
                        payload["score"],
                        json.dumps(payload["identity_keys"]),
                        payload["title_key"],
                        payload["topic_key"],
                    ),
                )

    def record_source_statuses(self, run_id: str, statuses: list[main.SourceStatus]) -> None:
        with self._transaction():
            self._execute("DELETE FROM source_metrics WHERE report_run_id = ?", (run_id,))
            for status in statuses:
                self._execute(
                    """
                    INSERT INTO source_metrics (
                        id, report_run_id, source_name, success, item_count, error_summary, duration_ms, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        _new_id("src"),
                        run_id,
                        status.name,
                        int(status.success),
                        status.item_count,
                        status.error[:500],
                        _timestamp(),
                    ),
                )
