"""Generate validated, editable research-profile recommendations."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import main

from personalization.models import (
    ProfileRecommendation,
    RecommendationRequest,
    ResearchProfileInput,
    ScheduleInput,
)
from personalization.source_catalog import TRUSTED_SOURCE_LAYERS, source_definitions_for_profile


class RecommendationError(RuntimeError):
    """Raised when a recommendation cannot be safely constructed."""


_RESPONSE_FIELDS = frozenset(
    {
        "base_profile",
        "research_focus",
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


def automatic_source_ids(base_profile: str) -> tuple[str, ...]:
    """Return the safe, already-registered sources an AI may recommend.

    Manual source selection has a wider scope: an operator may explicitly opt
    into a community signal.  Model recommendations deliberately do not have
    that authority, and never introduce a key-gated, restricted, directory-only
    or non-default source into a saved profile.
    """

    executable_ids = set(main.available_source_ids(base_profile))
    return tuple(
        source.id
        for source in source_definitions_for_profile(base_profile)
        if source.id in executable_ids
        and source.collectable
        and source.default_enabled
        and source.layer != "community_signal"
        and source.access_label == "公开可用"
    )


def automatic_source_layers(base_profile: str) -> tuple[str, ...]:
    """Return the evidence layers represented by safe automatic sources."""

    allowed_ids = set(automatic_source_ids(base_profile))
    return tuple(
        layer
        for layer in TRUSTED_SOURCE_LAYERS
        if any(
            source.id in allowed_ids and source.layer == layer
            for source in source_definitions_for_profile(base_profile)
        )
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
    source_catalogue = {profile: list(automatic_source_ids(profile)) for profile in supported_profiles}
    source_layer_catalogue = {
        profile: list(automatic_source_layers(profile)) for profile in supported_profiles
    }
    instructions = (
        "你是科研资讯日报的配置推荐助手。请充分分析用户研究方向，但不要输出分析过程、"
        "推理步骤或链式思维。只返回一个严格 JSON object，不要 Markdown、代码块或额外文字。"
        "推荐必须只使用提供的 profile、source、source layer、content preference 和 ISSN。"
        "社区信号、需要授权或 API Key 的来源、以及尚未接入抓取器的目录来源不能推荐。"
        "research_focus 必须是 4 到 60 个字符的清晰研究聚焦短语：可保留用户准确术语或忠实概括，"
        "不能包含“偏好”“信息来源”“优先级”“我想”或冒号。"
        "include_keywords 只放高相关核心词；optional_keywords 可放相邻议题、同义词、方法、应用"
        "或政策语境，供用户逐项选择，不能当作默认必选词。"
        "rationale 与 uncertainty 必须是简短中文说明。"
        "source_ids 与 optional_source_ids 必须严格从 supported_source_ids_by_profile 中 base_profile 对应列表选择；"
        "source_ids 只放高相关默认来源，optional_source_ids 只放可供用户勾选的扩展来源，两者不得重复。"
        "不得使用机构名称、会议名称或任何未列出的值。"
    )
    payload = {
        "research_topic": request.research_topic,
        "supported_profile_ids": supported_profiles,
        "supported_source_ids_by_profile": source_catalogue,
        "supported_source_layer_ids_by_profile": source_layer_catalogue,
        "supported_content_preferences": ["review", "mechanism", "methodology", "experiment"],
        "allowed_journal_issns_by_profile": journal_catalogue,
        "response_schema": {
            "base_profile": "one supported profile ID",
            "research_focus": "clear research focus, 4-60 characters; may faithfully retain user terminology",
            "include_keywords": ["strings"],
            "optional_keywords": ["optional related strings for operator selection"],
            "exclude_keywords": ["strings"],
            "source_ids": ["source IDs allowed for base_profile"],
            "optional_source_ids": ["optional source IDs for operator selection"],
            "source_layer_ids": ["non-community source layers allowed for base_profile"],
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
    optional_keywords = response.get("optional_keywords")
    if optional_keywords is not None and (
        not isinstance(optional_keywords, list)
        or not all(isinstance(item, str) for item in optional_keywords)
    ):
        raise RecommendationError("malformed model output: optional_keywords must be a list of strings")
    optional_source_ids = response.get("optional_source_ids")
    if optional_source_ids is not None and (
        not isinstance(optional_source_ids, list)
        or not all(isinstance(item, str) for item in optional_source_ids)
    ):
        raise RecommendationError("malformed model output: optional_source_ids must be a list of strings")
    if "source_layer_ids" in response:
        source_layers = response["source_layer_ids"]
        if not isinstance(source_layers, list) or not all(
            isinstance(item, str) for item in source_layers
        ):
            raise RecommendationError("malformed model output: source_layer_ids must be a list of strings")
    if isinstance(response["max_items"], bool) or not isinstance(response["max_items"], int):
        raise RecommendationError("malformed model output: max_items must be an integer")
    for field in (
        "research_focus",
        "frequency",
        "timezone",
        "local_send_time",
        "rationale",
        "uncertainty",
    ):
        if not isinstance(response[field], str):
            raise RecommendationError(f"malformed model output: {field} must be a string")
    weekday = response["weekday"]
    if weekday is not None and (isinstance(weekday, bool) or not isinstance(weekday, int)):
        raise RecommendationError("malformed model output: weekday must be an integer or null")


def _normalise_research_focus(value: str, _original_topic: str) -> str:
    focus = re.sub(r"\s+", " ", value).strip(" ：:；;。")
    if not 4 <= len(focus) <= 60:
        raise RecommendationError("research_focus must be concise (4-60 chars)")
    if any(marker in focus for marker in ("偏好", "信息来源", "优先级", "我想", "：", ":")):
        raise RecommendationError("research_focus contains configuration text")
    return focus


def _normalise_optional_keywords(value: object, core_keywords: tuple[str, ...]) -> tuple[str, ...]:
    """Return user-selectable related terms without silently altering a profile."""

    if value is None:
        return ()
    assert isinstance(value, list)
    seen = {keyword.casefold() for keyword in core_keywords}
    optional_keywords: list[str] = []
    for raw_value in value:
        assert isinstance(raw_value, str)
        keyword = re.sub(r"\s+", " ", raw_value).strip()
        if not keyword or keyword.casefold() in seen:
            continue
        seen.add(keyword.casefold())
        optional_keywords.append(keyword)
        if len(optional_keywords) == 12:
            break
    return tuple(optional_keywords)


def _normalise_optional_source_ids(
    value: object, selected_source_ids: list[str], base_profile: str
) -> tuple[str, ...]:
    """Keep optional sources separate until an operator explicitly selects them."""

    if value is None:
        return ()
    assert isinstance(value, list)
    allowed_ids = set(automatic_source_ids(base_profile))
    selected_ids = set(selected_source_ids)
    optional_source_ids: list[str] = []
    for source_id in value:
        assert isinstance(source_id, str)
        if source_id not in allowed_ids:
            raise RecommendationError(
                f"optional_source_ids contain unsupported automatic values for {base_profile}: {source_id}"
            )
        if source_id in selected_ids or source_id in optional_source_ids:
            continue
        optional_source_ids.append(source_id)
    return tuple(optional_source_ids)


def _build_recommendation(
    request: RecommendationRequest, response: dict[str, object], provider: str, model: str
) -> ProfileRecommendation:
    _require_response_shape(response)
    base_profile = response["base_profile"]
    assert isinstance(base_profile, str)
    if base_profile not in main.REPORT_PROFILES:
        raise RecommendationError("base_profile must be an existing report profile")
    research_focus = response["research_focus"]
    assert isinstance(research_focus, str)

    source_ids = response["source_ids"]
    assert isinstance(source_ids, list)
    if invalid_sources := set(source_ids) - set(automatic_source_ids(base_profile)):
        raise RecommendationError(
            f"source_ids contain unsupported automatic values for {base_profile}: "
            f"{', '.join(sorted(invalid_sources))}"
        )
    source_layer_ids = response.get("source_layer_ids", [])
    assert isinstance(source_layer_ids, list)
    if invalid_layers := set(source_layer_ids) - set(automatic_source_layers(base_profile)):
        raise RecommendationError(
            f"source_layer_ids contain unsupported automatic values for {base_profile}: "
            f"{', '.join(sorted(invalid_layers))}"
        )
    resolved_source_ids = list(source_ids)
    if (
        base_profile == "computer_science"
        and "ccf_conferences" in main.available_source_ids(base_profile)
        and "ccf_conferences" not in resolved_source_ids
    ):
        # Tier selection is an operator control, so the model only picks the
        # source. The shared input default provides the agreed A+B scope.
        resolved_source_ids.append("ccf_conferences")

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
            research_topic=_normalise_research_focus(research_focus, request.research_topic),
            include_keywords=response["include_keywords"],
            exclude_keywords=response["exclude_keywords"],
            source_ids=resolved_source_ids,
            source_layer_ids=source_layer_ids,
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
    return ProfileRecommendation(
        profile,
        schedule,
        rationale,
        uncertainty,
        _normalise_optional_keywords(response.get("optional_keywords"), profile.include_keywords),
        _normalise_optional_source_ids(
            response.get("optional_source_ids"), resolved_source_ids, base_profile
        ),
    )


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
    import logging
    LOGGER = logging.getLogger(__name__)
    for attempt in range(2):
        if request_json is None:
            response = _request_with_configured_client(instructions, user_prompt)
        else:
            try:
                response = request_json(instructions, user_prompt)
            except Exception as exc:
                raise RecommendationError("model response was not a valid JSON object") from exc
        if not isinstance(response, dict):
            raise RecommendationError("malformed model output: expected a JSON object")
        try:
            return _build_recommendation(request, response, config.provider, config.model)
        except RecommendationError as exc:
            err_msg = str(exc)
            if attempt == 0 and ("research_focus" in err_msg or "copied" in err_msg or "verbatim" in err_msg):
                LOGGER.warning("retrying recommendation after focus error: %s", err_msg)
                continue
            if attempt == 0:
                LOGGER.warning("retrying recommendation after: %s", err_msg)
                continue
            raise
