import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from .inflation import InflationFetchError, fetch_inflation_series
from .models import InflationRate, InflationSource


@dataclass
class InflationRefreshResult:
    source: InflationSource
    created_count: int
    updated_count: int
    record_count: int
    fetch_time: Optional[datetime]
    published_to_users: bool


logger = logging.getLogger(__name__)


def refresh_inflation_source(source: InflationSource) -> InflationRefreshResult:
    """
    Fetches CPI data for a source and upserts the series. Returns counts so the caller can log/output progress.
    """
    records = fetch_inflation_series(source.code)
    fetch_time = timezone.now()
    created_count = 0
    updated_count = 0

    if records:
        with transaction.atomic():
            for record in records:
                _, created_flag = InflationRate.objects.update_or_create(
                    source=source,
                    period=record.period,
                    defaults={
                        "index_value": record.index_value,
                        "metadata": record.metadata,
                        "fetched_at": fetch_time,
                    },
                )
                if created_flag:
                    created_count += 1
                else:
                    updated_count += 1
    published = False
    if records and not source.available_to_users:
        source.available_to_users = True
        source.save(update_fields=["available_to_users"])
        published = True
    return InflationRefreshResult(
        source=source,
        created_count=created_count,
        updated_count=updated_count,
        record_count=len(records),
        fetch_time=fetch_time if records else None,
        published_to_users=published,
    )


def get_last_month_start(reference_date: Optional[date] = None) -> date:
    """
    Returns the first day of the previous calendar month relative to the provided reference date (defaults to today).
    """
    reference_date = reference_date or timezone.now().date()
    first_of_month = reference_date.replace(day=1)
    previous_day = first_of_month - timedelta(days=1)
    return previous_day.replace(day=1)


def source_has_data_since(source: InflationSource, month_start: date) -> bool:
    """
    Checks whether a source has any inflation rate entries starting from the provided month (inclusive).
    """
    return source.rates.filter(period__gte=month_start).exists()


def ensure_recent_inflation_data(logger_instance=None) -> int:
    """
    Ensures all active inflation sources include data for the previous month. Returns the number of sources refreshed.
    """
    logger_ref = logger_instance or logger
    month_start = get_last_month_start()
    stale_sources = (
        InflationSource.objects.filter(is_active=True)
        .annotate(latest_period=Max("rates__period"))
        .filter(Q(latest_period__lt=month_start) | Q(latest_period__isnull=True))
    )
    refreshed = 0
    for source in stale_sources:
        try:
            result = refresh_inflation_source(source)
        except InflationFetchError as exc:
            logger_ref.warning("Automatic inflation refresh failed for %s: %s", source.code, exc)
            continue
        if not result.record_count:
            logger_ref.info("Automatic inflation refresh returned no rows for %s", source.code)
            continue
        refreshed += 1
    if refreshed == 0:
        logger_ref.debug("Automatic inflation refresh found all sources up to date for %s", month_start)
    return refreshed
