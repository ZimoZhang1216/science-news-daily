"""Compose user research preferences with existing fixed-profile defaults."""

from __future__ import annotations

import copy
import re
from typing import Any

import main

from personalization.models import ResearchProfileInput


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
    effective["title"] = f"{profile.research_topic} 科研资讯日报"
    effective["output_prefix"] = f"custom_{_safe_output_component(user_id)}"
    effective["email_env"] = "CUSTOM_REPORT_EMAIL_TO"
    effective["default_email_to"] = ""
    effective["allow_default_email_fallback"] = False
    effective["relevance_terms"] = list(
        dict.fromkeys([*effective["relevance_terms"], *profile.include_keywords])
    )
    effective["enabled_source_ids"] = profile.source_ids
    shared_query_terms = [
        profile.research_topic,
        *profile.include_keywords,
        *effective["relevance_terms"],
    ]
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

    haystack = f"{item.title} {item.abstract}".casefold()
    if any(_matches_keyword(haystack, term) for term in profile.exclude_keywords):
        return False
    return not profile.include_keywords or any(
        _matches_keyword(haystack, term) for term in profile.include_keywords
    )
