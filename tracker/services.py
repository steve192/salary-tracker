from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from django.utils import timezone

from .models import Employer, InflationRate, InflationSource, InflationSourceChoices, SalaryEntry, UserPreference


@dataclass
class TimelinePoint:
    period: date
    label: str
    base_amount: Decimal
    total_amount: Decimal
    employer_id: Optional[int]


@dataclass
class EmployerCompSummary:
    employer_id: int
    employer_name: str
    actual_total: Decimal
    inflation_total: Optional[Decimal]
    inflation_ready: bool
    inflation_message: Optional[str]
    delta_amount: Optional[Decimal]
    delta_state: Optional[str]


@dataclass
class InflationGap:
    start: date
    end: date


@dataclass
class InflationGapReport:
    source: str
    label: str
    missing_ranges: List[InflationGap]
    missing_months: int
    expected_months: int
    is_complete: bool


INFLATION_REASON_MESSAGES = {
    "no-regular-salary": "Add a regular salary entry to see the projection.",
    "no-inflation-data": "Download inflation data in Settings to compare.",
    "missing-baseline-index": "Inflation data missing for the first salary month.",
    "missing-series-data": "Inflation data missing for part of this period.",
    "no-source-selected": "Select an inflation source in Settings to enable this comparison.",
}


def _iter_months(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current = _next_month(current)


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _prev_month(value: date) -> date:
    if value.month == 1:
        return date(value.year - 1, 12, 1)
    return date(value.year, value.month - 1, 1)


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _last_complete_month(reference: date) -> Optional[date]:
    month_start = _month_start(reference)
    if month_start.year == 1 and month_start.month == 1:
        return None
    return _prev_month(month_start)


def _month_span_count(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


def _inflation_projection(
    user,
    timeline: List[TimelinePoint],
    window: Tuple[date, date],
    baseline_mode: Optional[str],
    source: Optional[InflationSource],
) -> Tuple[List[float | None], Dict[str, str | float | bool | None]]:
    meta: Dict[str, str | float | bool | None] = {
        "ready": False,
        "source": source.label if source else None,
        "reason": None,
        "baseLabel": None,
        "baseSalary": None,
        "mode": baseline_mode,
    }
    if not timeline:
        meta["reason"] = "missing-timeline"
        return [], meta

    if not source:
        meta["reason"] = "no-source-selected"
        return [], meta

    start_date, end_date = window
    rates = (
        InflationRate.objects.filter(
            source=source,
            period__gte=start_date,
            period__lte=end_date,
        )
        .only("period", "index_value")
        .order_by("period")
    )
    rate_map = {rate.period: rate.index_value for rate in rates}

    baseline_mode = baseline_mode or UserPreference.InflationBaselineMode.GLOBAL
    meta["mode"] = baseline_mode
    per_employer_mode = baseline_mode == UserPreference.InflationBaselineMode.PER_EMPLOYER

    first_salary_point: Optional[TimelinePoint] = None
    base_index: Optional[Decimal] = None
    per_employer_points: Dict[int, TimelinePoint] = {}
    per_employer_base_index: Dict[int, Decimal] = {}

    if per_employer_mode:
        for point in timeline:
            if point.employer_id and point.base_amount > 0 and point.employer_id not in per_employer_points:
                per_employer_points[point.employer_id] = point
                idx = rate_map.get(point.period)
                if idx:
                    per_employer_base_index[point.employer_id] = idx
        if not per_employer_points:
            meta["reason"] = "no-regular-salary"
            return [], meta
        if len(per_employer_base_index) != len(per_employer_points):
            meta["reason"] = "missing-baseline-index"
            return [], meta
    else:
        first_salary_point = next((point for point in timeline if point.base_amount > 0), None)
        if not first_salary_point:
            meta["reason"] = "no-regular-salary"
            return [], meta
        base_index = rate_map.get(first_salary_point.period)
        if not base_index:
            meta["reason"] = "missing-baseline-index"
            return [], meta

    inflation_series: List[float | None] = []
    quantizer = Decimal("0.01")
    for point in timeline:
        if per_employer_mode:
            employer_id = point.employer_id
            base_point = per_employer_points.get(employer_id) if employer_id else None
            base_idx = per_employer_base_index.get(employer_id) if employer_id else None
        else:
            base_point = first_salary_point
            base_idx = base_index

        if not base_point or not base_idx:
            inflation_series.append(None)
            continue

        period_index = rate_map.get(point.period)
        if not period_index:
            inflation_series.append(None)
            continue

        multiplier = period_index / base_idx
        inflation_value = (base_point.base_amount * multiplier).quantize(quantizer)
        inflation_series.append(float(inflation_value))

    if not any(value is not None for value in inflation_series):
        meta["reason"] = "missing-series-data"
        return inflation_series, meta

    if per_employer_mode:
        meta.update(
            {
                "ready": True,
                "reason": None,
                "baseLabel": None,
                "baseSalary": None,
            }
        )
    else:
        meta.update(
            {
                "ready": True,
                "reason": None,
                "baseLabel": first_salary_point.label if first_salary_point else None,
                "baseSalary": float(first_salary_point.base_amount) if first_salary_point else None,
            }
        )
    return inflation_series, meta


def build_salary_timeline(
    user,
    baseline_mode: Optional[str] = None,
    inflation_source: Optional[InflationSource] = None,
) -> Dict[str, List]:
    preferences = None
    if baseline_mode is None or inflation_source is None:
        preferences, _ = UserPreference.objects.get_or_create(user=user)
        if baseline_mode is None:
            baseline_mode = preferences.inflation_baseline_mode
        if inflation_source is None:
            inflation_source = preferences.inflation_source

    entries = list(
        SalaryEntry.objects.filter(user=user)
        .select_related("employer")
        .order_by("effective_date", "created_at")
    )
    if not entries:
        return {
            "labels": [],
            "baseSeries": [],
            "totalSeries": [],
            "bonusWindows": [],
            "inflationSeries": [],
            "inflationMeta": {
                "ready": False,
                "source": inflation_source.label if inflation_source else None,
                "reason": "missing-timeline",
                "baseLabel": None,
                "baseSalary": None,
                "mode": baseline_mode,
            },
            "employerSwitches": [],
        }

    start_date = _month_start(entries[0].effective_date)
    latest_relevant = max(entry.end_date or timezone.now().date() for entry in entries)
    end_date = _month_start(latest_relevant)

    regular_entries = [entry for entry in entries if entry.entry_type == SalaryEntry.EntryType.REGULAR]
    bonus_entries = [entry for entry in entries if entry.entry_type == SalaryEntry.EntryType.BONUS]
    employer_name_map = {entry.employer_id: entry.employer.name for entry in entries}

    timeline: List[TimelinePoint] = []
    employer_switches: List[Dict[str, str]] = []
    active_regular = None
    regular_index = 0
    previous_employer_id = None

    current = start_date
    while current <= end_date:
        while regular_index < len(regular_entries) and regular_entries[regular_index].effective_date <= current:
            active_regular = regular_entries[regular_index]
            regular_index += 1
        if active_regular and active_regular.end_date and active_regular.end_date < current:
            active_regular = None

        base_amount = active_regular.amount if active_regular else Decimal("0")
        bonus_total = Decimal("0")
        current_employer_id = active_regular.employer_id if active_regular else None
        if current_employer_id and current_employer_id != previous_employer_id:
            employer_switches.append(
                {
                    "label": current.strftime("%b %Y"),
                    "employer": employer_name_map.get(current_employer_id, "Employer change"),
                }
            )
        previous_employer_id = current_employer_id

        for bonus in bonus_entries:
            bonus_start = _month_start(bonus.effective_date)
            bonus_end = _month_start(bonus.end_date)
            if bonus_start <= current <= bonus_end:
                months = max(1, _month_span_count(bonus_start, bonus_end))
                bonus_total += bonus.amount / months

        label = current.strftime("%b %Y")
        timeline.append(TimelinePoint(current, label, base_amount, base_amount + bonus_total, current_employer_id))
        current = _next_month(current)

    bonus_windows = [
        {
            "employer": bonus.employer.name,
            "start": bonus.effective_date.isoformat(),
            "end": bonus.end_date.isoformat() if bonus.end_date else None,
        }
        for bonus in bonus_entries
    ]

    inflation_series, inflation_meta = _inflation_projection(user, timeline, (start_date, end_date), baseline_mode, inflation_source)

    return {
        "labels": [point.label for point in timeline],
        "baseSeries": [float(point.base_amount) for point in timeline],
        "totalSeries": [float(point.total_amount) for point in timeline],
        "bonusWindows": bonus_windows,
        "inflationSeries": inflation_series,
        "inflationMeta": inflation_meta,
        "employerSwitches": employer_switches,
    }


def _first_regular_entry(entries: List[SalaryEntry]) -> Optional[SalaryEntry]:
    regular_entries = [entry for entry in entries if entry.entry_type == SalaryEntry.EntryType.REGULAR]
    if not regular_entries:
        return None
    regular_entries.sort(key=lambda entry: (entry.effective_date, entry.created_at))
    return regular_entries[0]


def _resolved_end_date(entry: SalaryEntry, derived_end_dates: Dict[int, Optional[date]]) -> Optional[date]:
    return derived_end_dates.get(entry.id) if entry.id in derived_end_dates else entry.end_date


def _compute_actual_total(
    entries: List[SalaryEntry],
    cutoff_period: Optional[date],
    derived_end_dates: Optional[Dict[int, Optional[date]]] = None,
) -> Tuple[Decimal, Optional[date]]:
    quantizer = Decimal("0.01")
    if cutoff_period is None:
        return Decimal("0.00"), None
    scoped_entries = [entry for entry in entries if entry.effective_date <= cutoff_period]
    if not scoped_entries:
        return Decimal("0.00"), None

    start_date = _month_start(min(entry.effective_date for entry in scoped_entries))
    if start_date > cutoff_period:
        return Decimal("0.00"), None
    derived_end_dates = derived_end_dates or {}

    regular_entries = [entry for entry in scoped_entries if entry.entry_type == SalaryEntry.EntryType.REGULAR]
    bonus_entries = [entry for entry in scoped_entries if entry.entry_type == SalaryEntry.EntryType.BONUS]
    regular_entries.sort(key=lambda entry: (entry.effective_date, entry.created_at))
    bonus_entries.sort(key=lambda entry: (entry.effective_date, entry.created_at))

    total_amount = Decimal("0")
    active_regular = None
    regular_index = 0
    current = start_date
    last_active_period: Optional[date] = None

    while current <= cutoff_period:
        while regular_index < len(regular_entries) and regular_entries[regular_index].effective_date <= current:
            active_regular = regular_entries[regular_index]
            regular_index += 1
        if active_regular:
            resolved_end = _resolved_end_date(active_regular, derived_end_dates)
            if resolved_end and _month_start(resolved_end) < current:
                active_regular = None

        base_amount = active_regular.amount if active_regular else Decimal("0")
        bonus_total = Decimal("0")
        for bonus in bonus_entries:
            bonus_start = _month_start(bonus.effective_date)
            bonus_end_raw = bonus.end_date or cutoff_period
            bonus_end = _month_start(min(bonus_end_raw, cutoff_period))
            if bonus_start <= current <= bonus_end:
                months = max(1, _month_span_count(bonus_start, bonus_end))
                bonus_total += bonus.amount / months

        if base_amount > 0 or bonus_total > 0:
            last_active_period = current
        total_amount += base_amount + bonus_total
        current = _next_month(current)

    return total_amount.quantize(quantizer), last_active_period


def _compute_inflation_total(
    first_regular: Optional[SalaryEntry],
    comparison_end: Optional[date],
    rate_map: Dict[date, Decimal],
) -> Tuple[Optional[Decimal], Optional[str]]:
    quantizer = Decimal("0.01")
    if not first_regular:
        return None, "no-regular-salary"
    if comparison_end is None:
        return Decimal("0.00"), None

    base_period = _month_start(first_regular.effective_date)
    if comparison_end < base_period:
        return Decimal("0.00"), None
    if not rate_map:
        return None, "no-inflation-data"

    base_index = rate_map.get(base_period)
    if not base_index:
        return None, "missing-baseline-index"

    total = Decimal("0")
    for period in _iter_months(base_period, comparison_end):
        period_index = rate_map.get(period)
        if not period_index:
            return None, "missing-series-data"
        multiplier = period_index / base_index
        total += first_regular.amount * multiplier

    return total.quantize(quantizer), None


def build_employer_compensation_summary(
    user,
    employers: Optional[Iterable[Employer]] = None,
    preferences: Optional[UserPreference] = None,
    inflation_source: Optional[InflationSource] = None,
) -> List[EmployerCompSummary]:
    employer_list = list(employers) if employers is not None else list(Employer.objects.filter(user=user).order_by("name"))
    if not employer_list:
        return []

    if preferences is None:
        preferences, _ = UserPreference.objects.get_or_create(user=user)
    if inflation_source is None:
        inflation_source = preferences.inflation_source

    employer_ids = [employer.id for employer in employer_list]
    entries = list(
        SalaryEntry.objects.filter(user=user, employer_id__in=employer_ids)
        .select_related("employer")
        .order_by("employer_id", "effective_date", "created_at")
    )
    entries_by_employer: Dict[int, List[SalaryEntry]] = {employer_id: [] for employer_id in employer_ids}
    for entry in entries:
        entries_by_employer.setdefault(entry.employer_id, []).append(entry)

    all_regular_entries = [entry for entry in entries if entry.entry_type == SalaryEntry.EntryType.REGULAR]
    all_regular_entries.sort(key=lambda entry: (entry.effective_date, entry.created_at))
    derived_end_dates: Dict[int, Optional[date]] = {}
    for idx, entry in enumerate(all_regular_entries):
        if idx + 1 >= len(all_regular_entries):
            continue
        next_entry = all_regular_entries[idx + 1]
        next_start = next_entry.effective_date
        natural_end = entry.end_date
        if natural_end is None or natural_end >= next_start:
            derived_end = next_start - timedelta(days=1)
            if derived_end < entry.effective_date:
                derived_end = entry.effective_date
            derived_end_dates[entry.id] = derived_end

    rate_map: Dict[date, Decimal] = {}
    if inflation_source:
        rate_map = {
            rate.period: rate.index_value
            for rate in InflationRate.objects.filter(source=inflation_source).only("period", "index_value")
        }
    today = timezone.now().date()
    cutoff_period = _last_complete_month(today)
    summaries: List[EmployerCompSummary] = []

    for employer in employer_list:
        employer_entries = entries_by_employer.get(employer.id, [])
        actual_total, comparison_end = _compute_actual_total(employer_entries, cutoff_period, derived_end_dates)
        first_regular = _first_regular_entry(employer_entries)
        if not inflation_source:
            inflation_total = None
            inflation_reason = "no-source-selected"
        else:
            inflation_total, inflation_reason = _compute_inflation_total(first_regular, comparison_end, rate_map)
        inflation_ready = inflation_reason is None
        message = None if inflation_ready else INFLATION_REASON_MESSAGES.get(inflation_reason, "Inflation projection unavailable.")
        delta_amount = None
        delta_state = None
        if inflation_ready and inflation_total is not None:
            delta_amount = (actual_total - inflation_total).quantize(Decimal("0.01"))
            if delta_amount > 0:
                delta_state = "gain"
            elif delta_amount < 0:
                delta_state = "loss"
            else:
                delta_state = "even"
        summaries.append(
            EmployerCompSummary(
                employer_id=employer.id,
                employer_name=employer.name,
                actual_total=actual_total,
                inflation_total=inflation_total,
                inflation_ready=inflation_ready,
                inflation_message=message,
                delta_amount=delta_amount,
                delta_state=delta_state,
            )
        )

    return summaries


def build_inflation_gap_report(user) -> Dict[str, object]:
    salary_qs = SalaryEntry.objects.filter(user=user)
    if not salary_qs.exists():
        return {"has_salary_data": False, "start_period": None, "end_period": None, "sources": []}

    entry_dates = list(salary_qs.values_list("effective_date", "end_date"))
    start_period = _month_start(min(effective for effective, _ in entry_dates))
    today = timezone.now().date()
    latest_relevant = max((end or today) for _, end in entry_dates)
    end_period = _month_start(max(latest_relevant, today))

    expected_months = _month_span_count(start_period, end_period)
    reports: List[InflationGapReport] = []

    for source in InflationSource.objects.filter(is_active=True, available_to_users=True).order_by("label"):
        rate_periods = set(
            InflationRate.objects.filter(source=source, period__gte=start_period, period__lte=end_period).values_list("period", flat=True)
        )
        missing_ranges: List[InflationGap] = []
        missing_months = 0
        if expected_months:
            gap_start = None
            for period in _iter_months(start_period, end_period):
                if period not in rate_periods:
                    if gap_start is None:
                        gap_start = period
                else:
                    if gap_start is not None:
                        gap_end = _prev_month(period)
                        missing_months += _month_span_count(gap_start, gap_end)
                        missing_ranges.append(InflationGap(gap_start, gap_end))
                        gap_start = None
            if gap_start is not None:
                missing_months += _month_span_count(gap_start, end_period)
                missing_ranges.append(InflationGap(gap_start, end_period))

        reports.append(
            InflationGapReport(
                source=source.code,
                label=source.label,
                missing_ranges=missing_ranges,
                missing_months=missing_months,
                expected_months=expected_months,
                is_complete=expected_months > 0 and missing_months == 0 and bool(rate_periods),
            )
        )

    return {
        "has_salary_data": True,
        "start_period": start_period,
        "end_period": end_period,
        "sources": reports,
    }
