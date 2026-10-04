"""Operational recency policy; age is a review signal, not a clinical verdict."""

from datetime import date
from enum import StrEnum


class FreshnessState(StrEnum):
    CURRENT = 'CURRENT'
    AGING = 'AGING'
    STALE = 'STALE'
    SUPERSEDED = 'SUPERSEDED'
    WITHDRAWN = 'WITHDRAWN'


_MEDICINE = {'medication', 'medicine', 'drug', 'metformin', 'amoxicillin',
             'paracetamol', 'antibiotic', 'dosage', 'contraindication',
             'approval', 'recall', 'warning'}
_CHANGING = {'recall', 'warning', 'withdrawn', 'approval', 'outbreak',
             'vaccination', 'vaccine', 'current', 'latest', 'recent',
             'safety', 'contraindication', 'interaction', 'interact'}


def topic_sensitive(terms: str) -> bool:
    words = set(terms.split())
    return bool(words & _CHANGING or
                (words & _MEDICINE and words & {'effects', 'treatment', 'safety'}))


def medicine_safety(terms: str) -> bool:
    words = set(terms.split())
    return bool(words & _MEDICINE and words & (_CHANGING | {'effects'}))


def classify(*, version_status: str, source_type: str,
             freshness_class: str, review_interval_days: int,
             update_status: str, effective_date: date | None,
             publication_date: date | None, sensitive: bool,
             issuing_organization: str = '',
             today: date | None = None) -> FreshnessState:
    if version_status == 'SUPERSEDED':
        return FreshnessState.SUPERSEDED
    if version_status in {'WITHDRAWN', 'RETIRED'}:
        return FreshnessState.WITHDRAWN
    if version_status != 'ACTIVE' or update_status == 'UPDATE_AVAILABLE':
        return FreshnessState.STALE
    age_date = effective_date or publication_date
    if age_date is None:
        return FreshnessState.AGING if sensitive else FreshnessState.CURRENT
    interval = review_interval_days
    if source_type == 'PUBLIC_HEALTH':
        interval = min(interval, 90)
    if any(name in issuing_organization.casefold() for name in
           ('disease control', 'drug administration', 'food and drug administration')):
        interval = min(interval, 90)
    if freshness_class == 'SENSITIVE' or sensitive:
        interval = min(interval, 90)
    elif freshness_class == 'STABLE':
        interval = max(interval, 730)
    age = max(0, ((today or date.today()) - age_date).days)
    if age > interval * 2 or (sensitive and age > interval):
        return FreshnessState.STALE
    if age > interval:
        return FreshnessState.AGING
    return FreshnessState.CURRENT
