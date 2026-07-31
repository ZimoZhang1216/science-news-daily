"""Validated inputs shared by the local operations dashboard and workflow runner."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time
from email.utils import parseaddr
from typing import Literal, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import main
from personalization.source_catalog import TRUSTED_SOURCE_LAYERS


UserStatus = Literal["active", "paused", "expired"]
Frequency = Literal["daily", "weekdays", "weekly"]

_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_SOURCE_IDS = main.SUPPORTED_SOURCE_IDS
_CONTENT_PREFERENCES = frozenset({"review", "mechanism", "methodology", "experiment"})
_OUTPUT_FORMATS = frozenset({"docx", "pdf"})
_LLM_PROVIDERS = frozenset({"openai", "deepseek", "openrouter"})
_CCF_TIER_ORDER = {"A": 0, "B": 1, "C": 2}


def _normalise_string_list(value: str | Sequence[str], *, casefold: bool = True) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_values = re.split(r"[,;\n]", value)
    else:
        raw_values = [str(item) for item in value]

    normalised: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        clean_value = raw_value.strip()
        if not clean_value:
            continue
        comparison_value = clean_value.casefold() if casefold else clean_value
        if comparison_value in seen:
            continue
        seen.add(comparison_value)
        normalised.append(comparison_value)
    return tuple(normalised)


def _normalise_ccf_conference_tiers(value: str | Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_values = re.split(r"[,;\n]", value)
    else:
        raw_values = [str(item) for item in value]

    tiers = tuple(raw_value.strip().upper() for raw_value in raw_values if raw_value.strip())
    if not tiers or any(tier not in _CCF_TIER_ORDER for tier in tiers):
        raise ValueError("ccf_conference_tiers must be a non-empty subset of A, B, and C")
    if len(set(tiers)) != len(tiers) or tuple(sorted(tiers, key=_CCF_TIER_ORDER.__getitem__)) != tiers:
        raise ValueError("ccf_conference_tiers must be ordered without duplicates")
    return tiers


def validate_timezone(value: str) -> str:
    timezone = value.strip()
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc
    return timezone


def validate_email(value: str) -> str:
    email = value.strip()
    _, parsed_address = parseaddr(email)
    if parsed_address != email or not _EMAIL_PATTERN.fullmatch(email):
        raise ValueError("email must be a valid email address")
    return email


@dataclass(frozen=True)
class UserInput:
    display_name: str
    email: str
    status: UserStatus

    @classmethod
    def from_form(cls, display_name: str, email: str, status: str) -> "UserInput":
        clean_name = display_name.strip()
        if not clean_name:
            raise ValueError("display_name is required")
        if status not in {"active", "paused", "expired"}:
            raise ValueError("status must be active, paused, or expired")
        return cls(display_name=clean_name, email=validate_email(email), status=status)


@dataclass(frozen=True)
class RecommendationRequest:
    display_name: str
    email: str
    research_topic: str

    @classmethod
    def from_form(cls, display_name: str, email: str, research_topic: str) -> "RecommendationRequest":
        user = UserInput.from_form(display_name, email, "active")
        topic = research_topic.strip()
        if not topic:
            raise ValueError("research_topic is required")
        return cls(user.display_name, user.email, topic)


@dataclass(frozen=True)
class ResearchProfileInput:
    base_profile: str
    research_topic: str
    include_keywords: tuple[str, ...]
    exclude_keywords: tuple[str, ...]
    source_ids: tuple[str, ...]
    journal_ids: tuple[str, ...]
    content_preferences: tuple[str, ...]
    max_items: int
    lookback_days: int
    ccf_conference_tiers: tuple[str, ...]
    llm_provider: str
    llm_model: str
    output_formats: tuple[str, ...]
    source_layer_ids: tuple[str, ...] = ()

    @classmethod
    def from_form(
        cls,
        *,
        base_profile: str,
        research_topic: str,
        include_keywords: str | Sequence[str],
        exclude_keywords: str | Sequence[str],
        source_ids: str | Sequence[str],
        journal_ids: str | Sequence[str],
        content_preferences: str | Sequence[str],
        max_items: int,
        llm_provider: str,
        llm_model: str,
        output_formats: str | Sequence[str],
        lookback_days: int = 3,
        ccf_conference_tiers: str | Sequence[str] = ("A", "B"),
        source_layer_ids: str | Sequence[str] = (),
    ) -> "ResearchProfileInput":
        if base_profile not in main.REPORT_PROFILES:
            raise ValueError("base_profile must be an existing report profile")
        clean_topic = research_topic.strip()
        if not clean_topic:
            raise ValueError("research_topic is required")
        if not 1 <= max_items <= 50:
            raise ValueError("max_items must be between 1 and 50")
        if isinstance(lookback_days, bool) or not isinstance(lookback_days, int) or not 1 <= lookback_days <= 60:
            raise ValueError("lookback_days must be between 1 and 60")

        normalised_sources = _normalise_string_list(source_ids)
        invalid_sources = set(normalised_sources) - _SOURCE_IDS
        if invalid_sources:
            raise ValueError(f"source_ids contain unsupported values: {', '.join(sorted(invalid_sources))}")
        if "ccf_conferences" in normalised_sources and base_profile != "computer_science":
            raise ValueError("ccf_conferences is only available for computer_science")

        normalised_source_layers = _normalise_string_list(source_layer_ids)
        invalid_source_layers = set(normalised_source_layers) - set(TRUSTED_SOURCE_LAYERS)
        if invalid_source_layers:
            raise ValueError(
                "source_layer_ids contain unsupported values: "
                f"{', '.join(sorted(invalid_source_layers))}"
            )

        normalised_preferences = _normalise_string_list(content_preferences)
        invalid_preferences = set(normalised_preferences) - _CONTENT_PREFERENCES
        if invalid_preferences:
            raise ValueError(
                "content_preferences contain unsupported values: "
                f"{', '.join(sorted(invalid_preferences))}"
            )

        provider = llm_provider.strip().casefold()
        if provider not in _LLM_PROVIDERS:
            raise ValueError("llm_provider must be openai or deepseek")
        model = llm_model.strip()
        if not model:
            raise ValueError("llm_model is required")

        normalised_formats = _normalise_string_list(output_formats)
        if not normalised_formats:
            raise ValueError("output_formats must include docx or pdf")
        invalid_formats = set(normalised_formats) - _OUTPUT_FORMATS
        if invalid_formats:
            raise ValueError(
                f"output_formats contain unsupported values: {', '.join(sorted(invalid_formats))}"
            )

        return cls(
            base_profile=base_profile,
            research_topic=clean_topic,
            include_keywords=_normalise_string_list(include_keywords),
            exclude_keywords=_normalise_string_list(exclude_keywords),
            source_ids=normalised_sources,
            journal_ids=_normalise_string_list(journal_ids, casefold=False),
            content_preferences=normalised_preferences,
            max_items=max_items,
            lookback_days=lookback_days,
            ccf_conference_tiers=_normalise_ccf_conference_tiers(ccf_conference_tiers),
            llm_provider=provider,
            llm_model=model,
            output_formats=normalised_formats,
            source_layer_ids=normalised_source_layers,
        )


@dataclass(frozen=True)
class ScheduleInput:
    frequency: Frequency
    weekday: int | None
    timezone: str
    local_send_time: time
    enabled: bool

    @classmethod
    def from_form(
        cls,
        frequency: str,
        weekday: int | None,
        timezone: str,
        local_send_time: str,
        enabled: bool,
    ) -> "ScheduleInput":
        if frequency not in {"daily", "weekdays", "weekly"}:
            raise ValueError("frequency must be daily, weekdays, or weekly")
        if frequency == "weekly":
            if weekday is None or not 0 <= weekday <= 6:
                raise ValueError("weekday must be between 0 and 6 for weekly schedules")
        elif weekday is not None:
            raise ValueError("weekday is only allowed for weekly schedules")
        if not _TIME_PATTERN.fullmatch(local_send_time):
            raise ValueError("local_send_time must use HH:MM")
        return cls(
            frequency=frequency,
            weekday=weekday,
            timezone=validate_timezone(timezone),
            local_send_time=time.fromisoformat(local_send_time),
            enabled=bool(enabled),
        )


@dataclass(frozen=True)
class ProfileRecommendation:
    profile: ResearchProfileInput
    schedule: ScheduleInput
    rationale: str
    uncertainty: str

    def __post_init__(self) -> None:
        if self.schedule.enabled:
            raise ValueError("schedule.enabled must be False")
