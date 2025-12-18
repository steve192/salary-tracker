from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable, Dict, Iterable, List, Optional, Tuple

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
class BaselineSetup:
    selector: Callable[[TimelinePoint], Tuple[Optional[TimelinePoint], Optional[Decimal]]]
    base_label: Optional[str]
    base_salary: Optional[float]
    skip_prehistory: bool


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
    "manual-baseline-unset": "Select an inflation baseline entry in the salary table.",
    "manual-baseline-invalid": "The selected manual inflation baseline is no longer available.",
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


def _build_rate_map(source: InflationSource, start_date: date, end_date: date) -> Dict[date, Decimal]:
    rates = (
        InflationRate.objects.filter(source=source, period__gte=start_date, period__lte=end_date)
        .only("period", "index_value")
        .order_by("period")
    )
    return {rate.period: rate.index_value for rate in rates}


def _build_baseline_setup(
    timeline: List[TimelinePoint],
    baseline_mode: str,
    rate_map: Dict[date, Decimal],
    manual_entry: Optional[SalaryEntry],
) -> Tuple[Optional[BaselineSetup], Optional[str]]:
    if baseline_mode == UserPreference.InflationBaselineMode.PER_EMPLOYER:
        return _baseline_per_employer_setup(timeline, rate_map)
    if baseline_mode == UserPreference.InflationBaselineMode.MANUAL:
        return _baseline_manual_setup(timeline, rate_map, manual_entry)
    if baseline_mode == UserPreference.InflationBaselineMode.LAST_INCREASE:
        return _baseline_last_increase_setup(timeline, rate_map)
    return _baseline_global_setup(timeline, rate_map)


def _baseline_per_employer_setup(
    timeline: List[TimelinePoint],
    rate_map: Dict[date, Decimal],
) -> Tuple[Optional[BaselineSetup], Optional[str]]:
    per_employer_points: Dict[int, TimelinePoint] = {}
    per_employer_base_index: Dict[int, Decimal] = {}
    for point in timeline:
        if point.employer_id and point.base_amount > 0 and point.employer_id not in per_employer_points:
            per_employer_points[point.employer_id] = point
            idx = rate_map.get(point.period)
            if idx:
                per_employer_base_index[point.employer_id] = idx
    if not per_employer_points:
        return None, "no-regular-salary"
    if len(per_employer_base_index) != len(per_employer_points):
        return None, "missing-baseline-index"

    def selector(point: TimelinePoint) -> Tuple[Optional[TimelinePoint], Optional[Decimal]]:
        employer_id = point.employer_id
        return per_employer_points.get(employer_id), per_employer_base_index.get(employer_id)

    setup = BaselineSetup(selector=selector, base_label=None, base_salary=None, skip_prehistory=False)
    return setup, None


def _baseline_manual_setup(
    timeline: List[TimelinePoint],
    rate_map: Dict[date, Decimal],
    manual_entry: Optional[SalaryEntry],
) -> Tuple[Optional[BaselineSetup], Optional[str]]:
    if manual_entry is None or manual_entry.entry_type != SalaryEntry.EntryType.REGULAR:
        return None, "manual-baseline-unset"
    manual_period = _month_start(manual_entry.effective_date)
    selected_point = next((point for point in timeline if point.period == manual_period), None)
    if not selected_point or selected_point.base_amount <= 0:
        return None, "manual-baseline-invalid"
    base_index = rate_map.get(selected_point.period)
    if not base_index:
        return None, "missing-baseline-index"

    def selector(_: TimelinePoint) -> Tuple[Optional[TimelinePoint], Optional[Decimal]]:
        return selected_point, base_index

    setup = BaselineSetup(
        selector=selector,
        base_label=selected_point.label,
        base_salary=float(selected_point.base_amount),
        skip_prehistory=True,
    )
    return setup, None


def _baseline_last_increase_setup(
    timeline: List[TimelinePoint],
    rate_map: Dict[date, Decimal],
) -> Tuple[Optional[BaselineSetup], Optional[str]]:
    raise_points: Dict[date, TimelinePoint] = {}
    raise_indexes: Dict[date, Decimal] = {}
    previous_amount: Optional[Decimal] = None
    for point in timeline:
        if point.base_amount > 0 and (previous_amount is None or point.base_amount != previous_amount):
            idx = rate_map.get(point.period)
            if not idx:
                return None, "missing-baseline-index"
            raise_points[point.period] = point
            raise_indexes[point.period] = idx
            previous_amount = point.base_amount
    if not raise_points:
        return None, "no-regular-salary"

    base_map: Dict[date, Tuple[Optional[TimelinePoint], Optional[Decimal]]] = {}
    active_point: Optional[TimelinePoint] = None
    active_idx: Optional[Decimal] = None
    for point in timeline:
        maybe_raise = raise_points.get(point.period)
        if maybe_raise:
            active_point = maybe_raise
            active_idx = raise_indexes.get(point.period)
        base_map[point.period] = (active_point, active_idx)

    def selector(point: TimelinePoint) -> Tuple[Optional[TimelinePoint], Optional[Decimal]]:
        return base_map.get(point.period, (None, None))

    setup = BaselineSetup(selector=selector, base_label=None, base_salary=None, skip_prehistory=True)
    return setup, None


def _baseline_global_setup(
    timeline: List[TimelinePoint],
    rate_map: Dict[date, Decimal],
) -> Tuple[Optional[BaselineSetup], Optional[str]]:
    first_salary_point = next((point for point in timeline if point.base_amount > 0), None)
    if not first_salary_point:
        return None, "no-regular-salary"
    base_index = rate_map.get(first_salary_point.period)
    if not base_index:
        return None, "missing-baseline-index"

    def selector(_: TimelinePoint) -> Tuple[Optional[TimelinePoint], Optional[Decimal]]:
        return first_salary_point, base_index

    setup = BaselineSetup(
        selector=selector,
        base_label=first_salary_point.label,
        base_salary=float(first_salary_point.base_amount),
        skip_prehistory=True,
    )
    return setup, None


def _build_inflation_series(
    timeline: List[TimelinePoint],
    rate_map: Dict[date, Decimal],
    setup: BaselineSetup,
) -> List[float | None]:
    inflation_series: List[float | None] = []
    quantizer = Decimal("0.01")
    for point in timeline:
        base_point, base_idx = setup.selector(point)
        if not base_point or not base_idx:
            inflation_series.append(None)
            continue

        if setup.skip_prehistory and point.period < base_point.period:
            inflation_series.append(None)
            continue

        period_index = rate_map.get(point.period)
        if not period_index:
            inflation_series.append(None)
            continue

        multiplier = period_index / base_idx
        inflation_value = (base_point.base_amount * multiplier).quantize(quantizer)
        inflation_series.append(float(inflation_value))
    return inflation_series


def _inflation_projection(
    user,
    timeline: List[TimelinePoint],
    window: Tuple[date, date],
    baseline_mode: Optional[str],
    source: Optional[InflationSource],
    manual_entry: Optional[SalaryEntry] = None,
) -> Tuple[List[float | None], Dict[str, str | float | bool | None]]:
    meta: Dict[str, str | float | bool | None] = {
        "ready": False,
        "source": source.label if source else None,
        "reason": None,
        "baseLabel": None,
        "baseSalary": None,
        "mode": baseline_mode,
        "manualEntryId": manual_entry.id if manual_entry else None,
    }
    if not timeline:
        meta["reason"] = "missing-timeline"
        return [], meta

    if not source:
        meta["reason"] = "no-source-selected"
        return [], meta

    start_date, end_date = window
    rate_map = _build_rate_map(source, start_date, end_date)

    baseline_mode = baseline_mode or UserPreference.InflationBaselineMode.GLOBAL
    meta["mode"] = baseline_mode
    setup, reason = _build_baseline_setup(timeline, baseline_mode, rate_map, manual_entry)
    if reason or not setup:
        meta["reason"] = reason
        return [], meta

    inflation_series = _build_inflation_series(timeline, rate_map, setup)
    if not any(value is not None for value in inflation_series):
        meta["reason"] = "missing-series-data"
        return inflation_series, meta

    meta.update(
        {
            "ready": True,
            "reason": None,
            "baseLabel": setup.base_label,
            "baseSalary": setup.base_salary,
        }
    )
    return inflation_series, meta


def _resolve_timeline_inputs(
    user,
    baseline_mode: Optional[str],
    inflation_source: Optional[InflationSource],
    manual_entry: Optional[SalaryEntry],
) -> Tuple[Optional[str], Optional[InflationSource], Optional[SalaryEntry]]:
    resolved_mode = baseline_mode
    resolved_source = inflation_source
    resolved_manual = manual_entry
    if baseline_mode is None or inflation_source is None or manual_entry is None:
        preferences, _ = UserPreference.objects.get_or_create(user=user)
        if resolved_mode is None:
            resolved_mode = preferences.inflation_baseline_mode
        if resolved_source is None:
            resolved_source = preferences.inflation_source
        if resolved_manual is None:
            resolved_manual = preferences.inflation_manual_entry
    return resolved_mode, resolved_source, resolved_manual


def _empty_timeline_payload(
    baseline_mode: Optional[str],
    inflation_source: Optional[InflationSource],
    manual_entry: Optional[SalaryEntry],
) -> Dict[str, List]:
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
            "manualEntryId": manual_entry.id if manual_entry else None,
        },
        "employerSwitches": [],
    }


def _build_timeline_components(entries: List[SalaryEntry]) -> Tuple[
    List[TimelinePoint], date, date, List[Dict[str, Optional[str]]], List[Dict[str, str]]
]:
    start_date = _month_start(entries[0].effective_date)
    latest_relevant = max(entry.end_date or timezone.now().date() for entry in entries)
    end_date = _month_start(latest_relevant)
    regular_entries = [entry for entry in entries if entry.entry_type == SalaryEntry.EntryType.REGULAR]
    bonus_entries = [entry for entry in entries if entry.entry_type == SalaryEntry.EntryType.BONUS]
    employer_name_map = {entry.employer_id: entry.employer.name for entry in entries}
    timeline, employer_switches = _assemble_timeline_points(
        regular_entries,
        bonus_entries,
        start_date,
        end_date,
        employer_name_map,
    )
    bonus_windows = _build_bonus_windows(bonus_entries)
    return timeline, start_date, end_date, bonus_windows, employer_switches


def _assemble_timeline_points(
    regular_entries: List[SalaryEntry],
    bonus_entries: List[SalaryEntry],
    start_date: date,
    end_date: date,
    employer_name_map: Dict[int, str],
) -> Tuple[List[TimelinePoint], List[Dict[str, str]]]:
    timeline: List[TimelinePoint] = []
    employer_switches: List[Dict[str, str]] = []
    active_regular = None
    regular_index = 0
    previous_employer_id = None

    current = start_date
    while current <= end_date:
        active_regular, regular_index = _advance_regular_pointer(current, regular_entries, regular_index, active_regular)
        base_amount = active_regular.amount if active_regular else Decimal("0")
        bonus_total = _monthly_bonus_allocation(current, bonus_entries)
        current_employer_id = active_regular.employer_id if active_regular else None
        if current_employer_id and current_employer_id != previous_employer_id:
            employer_switches.append(
                {
                    "label": current.strftime("%b %Y"),
                    "employer": employer_name_map.get(current_employer_id, "Employer change"),
                }
            )
        previous_employer_id = current_employer_id
        label = current.strftime("%b %Y")
        timeline.append(TimelinePoint(current, label, base_amount, base_amount + bonus_total, current_employer_id))
        current = _next_month(current)
    return timeline, employer_switches


def _build_bonus_windows(bonus_entries: List[SalaryEntry]) -> List[Dict[str, Optional[str]]]:
    return [
        {
            "employer": bonus.employer.name,
            "start": bonus.effective_date.isoformat(),
            "end": bonus.end_date.isoformat() if bonus.end_date else None,
        }
        for bonus in bonus_entries
    ]


def _advance_regular_pointer(
    current: date,
    regular_entries: List[SalaryEntry],
    regular_index: int,
    active_regular: Optional[SalaryEntry],
    derived_end_dates: Optional[Dict[int, Optional[date]]] = None,
) -> Tuple[Optional[SalaryEntry], int]:
    while regular_index < len(regular_entries) and regular_entries[regular_index].effective_date <= current:
        active_regular = regular_entries[regular_index]
        regular_index += 1
    if active_regular:
        resolved_end = _resolved_end_date(active_regular, derived_end_dates or {})
        if resolved_end and _month_start(resolved_end) < current:
            active_regular = None
    return active_regular, regular_index


def _monthly_bonus_allocation(
    current: date,
    bonus_entries: List[SalaryEntry],
    cap_end: Optional[date] = None,
) -> Decimal:
    total = Decimal("0")
    for bonus in bonus_entries:
        bonus_start = _month_start(bonus.effective_date)
        raw_end = bonus.end_date or cap_end or bonus.effective_date
        if cap_end:
            raw_end = min(raw_end, cap_end)
        bonus_end = _month_start(raw_end)
        if bonus_start <= current <= bonus_end:
            months = max(1, _month_span_count(bonus_start, bonus_end))
            total += bonus.amount / months
    return total


def build_salary_timeline(
    user,
    baseline_mode: Optional[str] = None,
    inflation_source: Optional[InflationSource] = None,
    manual_entry: Optional[SalaryEntry] = None,
) -> Dict[str, List]:
    baseline_mode, inflation_source, manual_entry = _resolve_timeline_inputs(user, baseline_mode, inflation_source, manual_entry)

    entries = list(
        SalaryEntry.objects.filter(user=user)
        .select_related("employer")
        .order_by("effective_date", "created_at")
    )
    if not entries:
        return _empty_timeline_payload(baseline_mode, inflation_source, manual_entry)

    timeline, start_date, end_date, bonus_windows, employer_switches = _build_timeline_components(entries)

    inflation_series, inflation_meta = _inflation_projection(
        user,
        timeline,
        (start_date, end_date),
        baseline_mode,
        inflation_source,
        manual_entry=manual_entry,
    )

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
        active_regular, regular_index = _advance_regular_pointer(current, regular_entries, regular_index, active_regular, derived_end_dates)
        base_amount = active_regular.amount if active_regular else Decimal("0")
        bonus_total = _monthly_bonus_allocation(current, bonus_entries, cap_end=cutoff_period)

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
