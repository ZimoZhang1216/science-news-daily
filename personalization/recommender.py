"""Generate validated, editable research-profile recommendations."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import main

from personalization.models import (
    ProfileRecommendation,
    RecommendationRequest,
    ResearchProfileInput,
    ScheduleInput,
)


class RecommendationError(RuntimeError):
    """Raised when a recommendation cannot be safely constructed."""


_RESPONSE_FIELDS = frozenset(
    {
        "base_profile",
        "include_keywords",
        "exclude_keywords",
        "source_ids",
        "journal_ids",
        "content_preferences",
        "max_items",
        "output_formats",
        "frequency",
        "weekday",
        "timezone",
        "local_send_time",
        "rationale",
        "uncertainty",
    }
)
_LIST_RESPONSE_FIELDS = frozenset(
    {
        "include_keywords",
        "exclude_keywords",
        "source_ids",
        "journal_ids",
        "content_preferences",
        "output_formats",
    }
)


def allowed_journal_ids(base_profile: str) -> set[str]:
    """Return the Crossref ISSNs that the selected report profile supports."""

    return {
        issn
        for journal in main.resolve_profile(base_profile)["crossref_journals"]
        for issn in journal["issns"]
    }


def _prompt(request: RecommendationRequest) -> tuple[str, str]:
    supported_profiles = sorted(main.REPORT_PROFILES)
    journal_catalogue = {
        profile: sorted(allowed_journal_ids(profile)) for profile in supported_profiles
    }
    instructions = (
        "你是科研资讯日报的配置推荐助手。请充分分析用户研究方向，但不要输出分析过程、"
        "推理步骤或链式思维。只返回一个严格 JSON object，不要 Markdown、代码块或额外文字。"
        "推荐必须只使用提供的 profile、source、content preference 和 ISSN。"
        "rationale 与 uncertainty 必须是简短中文说明。"
    )
    payload = {
        "research_topic": request.research_topic,
        "supported_profile_ids": supported_profiles,
        "supported_source_ids": ["arxiv", "pubmed", "crossref", "rss"],
        "supported_content_preferences": ["review", "mechanism", "methodology", "experiment"],
        "allowed_journal_issns_by_profile": journal_catalogue,
        "response_schema": {
            "base_profile": "one supported profile ID",
            "include_keywords": ["strings"],
            "exclude_keywords": ["strings"],
            "source_ids": ["supported source IDs"],
            "journal_ids": ["ISSNs allowed for base_profile"],
            "content_preferences": ["supported content preferences"],
            "max_items": "integer from 1 to 50",
            "output_formats": ["docx and/or pdf"],
            "frequency": "daily, weekdays, or weekly",
            "weekday": "0-6 only when frequency is weekly; otherwise null",
            "timezone": "IANA timezone",
            "local_send_time": "HH:MM",
            "rationale": "short Chinese rationale",
            "uncertainty": "short Chinese uncertainty note",
        },
    }
    return instructions, json.dumps(payload, ensure_ascii=False)


def _require_response_shape(response: dict[str, object]) -> None:
    missing = _RESPONSE_FIELDS - response.keys()
    if missing:
        raise RecommendationError(f"malformed model output: missing {', '.join(sorted(missing))}")
    if not isinstance(response["base_profile"], str):
        raise RecommendationError("malformed model output: base_profile must be a string")
    for field in _LIST_RESPONSE_FIELDS:
        value = response[field]
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise RecommendationError(f"malformed model output: {field} must be a list of strings")
    if isinstance(response["max_items"], bool) or not isinstance(response["max_items"], int):
        raise RecommendationError("malformed model output: max_items must be an integer")
    for field in ("frequency", "timezone", "local_send_time", "rationale", "uncertainty"):
        if not isinstance(response[field], str):
            raise RecommendationError(f"malformed model output: {field} must be a string")
    weekday = response["weekday"]
    if weekday is not None and (isinstance(weekday, bool) or not isinstance(weekday, int)):
        raise RecommendationError("malformed model output: weekday must be an integer or null")


def _build_recommendation(
    request: RecommendationRequest, response: dict[str, object], provider: str, model: str
) -> ProfileRecommendation:
    _require_response_shape(response)
    base_profile = response["base_profile"]
    assert isinstance(base_profile, str)
    if base_profile not in main.REPORT_PROFILES:
        raise RecommendationError("base_profile must be an existing report profile")

    journal_ids = response["journal_ids"]
    assert isinstance(journal_ids, list)
    if invalid_journals := set(journal_ids) - allowed_journal_ids(base_profile):
        raise RecommendationError(
            f"journal_ids contain unsupported values for {base_profile}: "
            f"{', '.join(sorted(invalid_journals))}"
        )

    try:
        profile = ResearchProfileInput.from_form(
            base_profile=base_profile,
            research_topic=request.research_topic,
            include_keywords=response["include_keywords"],
            exclude_keywords=response["exclude_keywords"],
            source_ids=response["source_ids"],
            journal_ids=journal_ids,
            content_preferences=response["content_preferences"],
            max_items=response["max_items"],
            llm_provider=provider,
            llm_model=model,
            output_formats=response["output_formats"],
        )
        schedule = ScheduleInput.from_form(
            response["frequency"],
            response["weekday"],
            response["timezone"],
            response["local_send_time"],
            enabled=False,
        )
    except (TypeError, ValueError) as exc:
        raise RecommendationError(f"malformed model output: {exc}") from exc

    rationale = response["rationale"].strip()
    uncertainty = response["uncertainty"].strip()
    if not rationale or not uncertainty:
        raise RecommendationError("malformed model output: rationale and uncertainty are required")
    return ProfileRecommendation(profile, schedule, rationale, uncertainty)


def _request_with_configured_client(instructions: str, user_prompt: str) -> dict[str, object]:
    config = main.resolve_llm_config()
    if config is None:
        raise RecommendationError("configured LLM provider is unavailable")
    if main.OpenAI is None:
        raise RecommendationError("OpenAI-compatible client is unavailable")
    if not config.api_key:
        raise RecommendationError(f"missing credentials: configure {config.api_key_env}")

    client_kwargs: dict[str, str] = {"api_key": config.api_key}
    if config.base_url:
        client_kwargs["base_url"] = config.base_url
    try:
        request_kwargs: dict[str, Any] = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        create = main.OpenAI(**client_kwargs).chat.completions.create
        try:
            response = create(**request_kwargs)
        except Exception:  # noqa: BLE001 - compatible providers may reject JSON mode.
            request_kwargs.pop("response_format")
            response = create(**request_kwargs)
        response_text = getattr(main, "extract_response_text", main.chat_response_text)(response)
        parsed = main.parse_json_object(response_text)
    except RecommendationError:
        raise
    except Exception as exc:  # noqa: BLE001 - provider errors must not expose credentials.
        raise RecommendationError("model response was not a valid JSON object") from exc
    return parsed


def recommend_profile(
    request: RecommendationRequest,
    request_json: Callable[[str, str], dict[str, object]] | None = None,
) -> ProfileRecommendation:
    """Return a locally allowlisted, disabled-schedule recommendation.

    ``request_json`` is an injectable transport for tests; its two arguments are
    the system instruction and the JSON-encoded user prompt.
    """

    config = main.resolve_llm_config()
    if config is None:
        raise RecommendationError("configured LLM provider is unavailable")
    instructions, user_prompt = _prompt(request)
    if request_json is None:
        response = _request_with_configured_client(instructions, user_prompt)
    else:
        try:
            response = request_json(instructions, user_prompt)
        except Exception as exc:  # noqa: BLE001 - injected transport follows the same public error boundary.
            raise RecommendationError("model response was not a valid JSON object") from exc
    if not isinstance(response, dict):
        raise RecommendationError("malformed model output: expected a JSON object")
    return _build_recommendation(request, response, config.provider, config.model)
