import logging
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .inflation import (
    InflationFetchError,
    fetch_inflation_series,
    get_inflation_series_definition,
)
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
MIN_REFRESH_RECORD_RETENTION_RATIO = 0.9


def refresh_inflation_source(source: InflationSource) -> InflationRefreshResult:
    """
    Fetches CPI data for a source and upserts the series. Returns counts so the caller can log/output progress.
    """
    records = fetch_inflation_series(source.code)
    fetch_time = timezone.now()
    created_count = 0
    updated_count = 0

    if records:
        _validate_refresh_replacement(source, records)
        with transaction.atomic():
            _delete_stale_series_rows(source, records)
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


def _validate_refresh_replacement(source: InflationSource, records) -> None:
    incoming_periods = {record.period for record in records}
    if len(incoming_periods) != len(records):
        raise InflationFetchError("ECB service returned duplicate periods for this source.")

    existing_count = source.rates.count()
    if existing_count == 0:
        return

    # Refresh deletes rows that are absent from the fetched payload. If ECB returns
    # a partial response during an outage or starts paging this endpoint, deleting
    # the "missing" history would destroy valid local data.
    minimum_expected = math.ceil(existing_count * MIN_REFRESH_RECORD_RETENTION_RATIO)
    if len(records) < minimum_expected:
        raise InflationFetchError(
            f"Refusing to replace {existing_count} stored inflation rows with only {len(records)} fetched rows."
        )


def _delete_stale_series_rows(source: InflationSource, records) -> None:
    # ECB can retire or rebase HICP series. Treat a refresh as the source of truth
    # so rows from obsolete series/methodologies do not mix with current index data.
    source.rates.exclude(period__in=[record.period for record in records]).delete()


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


def source_has_current_series(source: InflationSource) -> bool:
    """
    Checks whether stored rows use the currently configured upstream series for this source.
    """
    series_definition = get_inflation_series_definition(source.code)
    if not series_definition:
        return True
    total_rows = source.rates.count()
    matching_rows = source.rates.filter(metadata__series_code=series_definition.series_code).count()
    return total_rows > 0 and matching_rows == total_rows


def ensure_recent_inflation_data(logger_instance=None) -> int:
    """
    Ensures all active inflation sources include data for the previous month. Returns the number of sources refreshed.
    """
    logger_ref = logger_instance or logger
    month_start = get_last_month_start()
    active_sources = InflationSource.objects.filter(is_active=True).annotate(latest_period=Max("rates__period"))
    refreshed = 0
    for source in active_sources:
        if source.latest_period and source.latest_period >= month_start and source_has_current_series(source):
            continue
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
