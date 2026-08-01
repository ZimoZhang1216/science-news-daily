"""Compose user research preferences with existing fixed-profile defaults."""

from __future__ import annotations

import copy
import re
from typing import Any

import main

from personalization.models import ResearchProfileInput
from personalization.source_catalog import default_source_ids_for_layers


_PREFERENCE_TERMS: dict[str, tuple[str, ...]] = {
    "review": ("review", "perspective"),
    "mechanism": ("mechanism", "pathway"),
    "methodology": ("method", "workflow", "platform"),
    "experiment": ("experiment", "assay", "in vivo"),
}


def _safe_output_component(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return clean or "user"


def _matches_keyword(haystack: str, keyword: str) -> bool:
    if re.fullmatch(r"[a-z0-9-]+", keyword):
        return main.contains_english_term(haystack, keyword)
    return keyword in haystack


def compose_effective_profile(profile: ResearchProfileInput, user_id: str) -> dict[str, Any]:
    """Create a user-specific copy while preserving existing subject behavior."""

    effective = copy.deepcopy(main.resolve_profile(profile.base_profile))
    effective["custom_user_id"] = user_id
    effective["output_prefix"] = f"custom_{_safe_output_component(user_id)}"
    effective["email_env"] = "CUSTOM_REPORT_EMAIL_TO"
    effective["default_email_to"] = ""
    effective["allow_default_email_fallback"] = False
    effective["relevance_terms"] = list(
        dict.fromkeys([*effective["relevance_terms"], *profile.include_keywords])
    )
    if profile.source_ids:
        effective["enabled_source_ids"] = profile.source_ids
    else:
        executable_source_ids = set(main.available_source_ids(profile.base_profile))
        effective["enabled_source_ids"] = tuple(
            source_id
            for source_id in default_source_ids_for_layers(profile.base_profile, profile.source_layer_ids)
            if source_id in executable_source_ids
        )
    effective["source_layer_ids"] = profile.source_layer_ids
    effective["source_selection_explicit"] = bool(profile.source_layer_ids or profile.source_ids)
    effective["ccf_conference_tiers"] = profile.ccf_conference_tiers
    # Research topics can be long free-form instructions. External source
    # queries use the structured keywords and bounded base-discipline terms
    # instead, while the full topic remains available for the report title.
    shared_query_terms = [*profile.include_keywords, *effective["relevance_terms"]]
    for field in ("arxiv_query_terms", "pubmed_query_terms", "openalex_query_terms", "community_query_terms"):
        effective[field] = list(dict.fromkeys([*effective.get(field, ()), *shared_query_terms]))
    effective["crossref_journals"] = [
        journal
        for journal in effective["crossref_journals"]
        if not profile.journal_ids
        or set(journal["issns"]).intersection(profile.journal_ids)
    ]
    effective["custom_preference_terms"] = tuple(
        term
        for preference in profile.content_preferences
        for term in _PREFERENCE_TERMS[preference]
    )
    effective["output_formats"] = profile.output_formats
    effective["llm_provider"] = profile.llm_provider
    effective["llm_model"] = profile.llm_model
    return effective


def item_matches_research_profile(item: main.NewsItem, profile: ResearchProfileInput) -> bool:
    """Apply user-selected include and exclude terms after base-profile collection."""

    if item_is_excluded_from_research_profile(item, profile):
        return False
    haystack = f"{item.title} {item.abstract}".casefold()
    return not profile.include_keywords or any(
        _matches_keyword(haystack, term) for term in profile.include_keywords
    )


def item_is_excluded_from_research_profile(item: main.NewsItem, profile: ResearchProfileInput) -> bool:
    """Keep explicit user exclusions in force for both strict and fallback selection."""

    haystack = f"{item.title} {item.abstract}".casefold()
    return any(_matches_keyword(haystack, term) for term in profile.exclude_keywords)
