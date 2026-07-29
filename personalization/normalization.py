"""Batch-normalise legacy user research profiles through the approved recommender."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from personalization.models import ProfileRecommendation, RecommendationRequest
from personalization.recommender import recommend_profile
from personalization.repository import PersonalizationRepository


@dataclass(frozen=True)
class ProfileNormalizationSummary:
    total: int
    normalized: int
    failed: int

    def as_dict(self) -> dict[str, int]:
        return {"total": self.total, "normalized": self.normalized, "failed": self.failed}


def normalize_existing_profiles(
    repository: PersonalizationRepository,
    *,
    recommender: Callable[[RecommendationRequest], ProfileRecommendation] = recommend_profile,
) -> ProfileNormalizationSummary:
    """Create one AI-normalised current version per user without touching schedules or history."""

    users = repository.list_users()
    normalized = failed = 0
    for user in users:
        try:
            current = repository.get_current_profile(user.id).input
            request = RecommendationRequest.from_form(
                user.display_name, user.email, current.research_topic
            )
            recommendation = recommender(request)
            repository.save_profile_version(user.id, recommendation.profile)
        except Exception:  # noqa: BLE001 - one stale or malformed profile must not block the batch.
            failed += 1
        else:
            normalized += 1
    return ProfileNormalizationSummary(total=len(users), normalized=normalized, failed=failed)
