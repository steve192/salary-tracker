from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from decimal import Decimal
from typing import Iterable, List

import requests

from .models import InflationSourceChoices

ECB_SERIES_TEMPLATE = "HICP.M.{country_code}.N.000000.4D0.INX"
ECB_BASE_URL = "https://data.ecb.europa.eu/data-detail-api/{series_code}"
ECB_OBSERVATION_KIND = "index"
ECB_EXPECTED_UNIT = "IX"
ECB_COUNTRY_CODES = {
    InflationSourceChoices.ECB_AUSTRIA.value: "AT",
    InflationSourceChoices.ECB_BELGIUM.value: "BE",
    InflationSourceChoices.ECB_BULGARIA.value: "BG",
    InflationSourceChoices.ECB_CROATIA.value: "HR",
    InflationSourceChoices.ECB_CYPRUS.value: "CY",
    InflationSourceChoices.ECB_CZECHIA.value: "CZ",
    InflationSourceChoices.ECB_DENMARK.value: "DK",
    InflationSourceChoices.ECB_ESTONIA.value: "EE",
    InflationSourceChoices.ECB_FINLAND.value: "FI",
    InflationSourceChoices.ECB_FRANCE.value: "FR",
    InflationSourceChoices.ECB_GERMANY.value: "DE",
    InflationSourceChoices.ECB_GREECE.value: "GR",
    InflationSourceChoices.ECB_HUNGARY.value: "HU",
    InflationSourceChoices.ECB_IRELAND.value: "IE",
    InflationSourceChoices.ECB_ITALY.value: "IT",
    InflationSourceChoices.ECB_LATVIA.value: "LV",
    InflationSourceChoices.ECB_LITHUANIA.value: "LT",
    InflationSourceChoices.ECB_LUXEMBOURG.value: "LU",
    InflationSourceChoices.ECB_MALTA.value: "MT",
    InflationSourceChoices.ECB_NETHERLANDS.value: "NL",
    InflationSourceChoices.ECB_POLAND.value: "PL",
    InflationSourceChoices.ECB_PORTUGAL.value: "PT",
    InflationSourceChoices.ECB_ROMANIA.value: "RO",
    InflationSourceChoices.ECB_SLOVAKIA.value: "SK",
    InflationSourceChoices.ECB_SLOVENIA.value: "SI",
    InflationSourceChoices.ECB_SPAIN.value: "ES",
    InflationSourceChoices.ECB_SWEDEN.value: "SE",
}
ECB_SERIES_BY_SOURCE = {
    code: ECB_SERIES_TEMPLATE.format(country_code=country_code)
    for code, country_code in ECB_COUNTRY_CODES.items()
}


class InflationFetchError(Exception):
    """Raised when an inflation feed cannot be fetched or parsed."""


@dataclass
class InflationRecord:
    period: date
    index_value: Decimal
    metadata: dict


@dataclass(frozen=True)
class InflationSeriesDefinition:
    series_code: str
    observation_kind: str
    expected_unit: str


@dataclass(frozen=True)
class ParsedObservation:
    period: date
    value: Decimal
    row: dict


ECB_SERIES_DEFINITIONS_BY_SOURCE = {
    code: InflationSeriesDefinition(
        series_code=series_code,
        observation_kind=ECB_OBSERVATION_KIND,
        expected_unit=ECB_EXPECTED_UNIT,
    )
    for code, series_code in ECB_SERIES_BY_SOURCE.items()
}


def fetch_inflation_series(source: str) -> List[InflationRecord]:
    series_definition = get_inflation_series_definition(source)
    if series_definition:
        return _fetch_ecb_series(series_definition)
    raise InflationFetchError("Unsupported inflation source.")


def get_inflation_series_definition(source: str) -> InflationSeriesDefinition | None:
    return ECB_SERIES_DEFINITIONS_BY_SOURCE.get(source)


def _fetch_ecb_series(series_definition: InflationSeriesDefinition) -> List[InflationRecord]:
    endpoint = ECB_BASE_URL.format(series_code=series_definition.series_code)
    try:
        response = requests.get(endpoint, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise InflationFetchError("Failed to reach ECB data service.") from exc

    payload = response.json()
    rows = _normalize_payload(payload)
    if not rows:
        raise InflationFetchError("ECB service returned no data.")

    observations = _parse_observations(rows)
    if not observations:
        raise InflationFetchError("ECB service returned no usable data.")

    _validate_index_observations(series_definition, observations)
    return _build_index_records(series_definition, observations)


def _parse_observations(rows: List[dict]) -> List[ParsedObservation]:
    observations: List[ParsedObservation] = []
    for row in rows:
        period_str = row.get("PERIOD") or row.get("period")
        observation_raw = _get_observation_value(row)
        if not period_str or observation_raw is None:
            continue
        try:
            period = datetime.strptime(period_str, "%Y-%m-%d").date()
        except ValueError as exc:
            raise InflationFetchError(f"Invalid period value '{period_str}'.") from exc
        observation_str = str(observation_raw).strip()
        if not observation_str or observation_str == "-":
            # Skip incomplete rows without a numeric observation.
            continue
        try:
            value = Decimal(observation_str)
        except Exception as exc:  # noqa: BLE001
            raise InflationFetchError(f"Invalid inflation observation value '{observation_raw}'.") from exc

        observations.append(ParsedObservation(period=period, value=value, row=row))

    observations.sort(key=lambda observation: observation.period)
    return observations


def _get_observation_value(row: dict):
    for key in ("OBS", "OBS_VALUE_AS_IS", "OBS_VALUE_ENTITY"):
        if key in row and row[key] is not None:
            return row[key]
    return None


def _validate_index_observations(
    series_definition: InflationSeriesDefinition,
    observations: List[ParsedObservation],
) -> None:
    for observation in observations:
        row = observation.row
        source_series = row.get("SERIES")
        if source_series != series_definition.series_code:
            raise InflationFetchError(
                f"Unexpected ECB series '{source_series}' for '{series_definition.series_code}'."
            )
        source_unit = row.get("UNIT")
        if source_unit != series_definition.expected_unit:
            raise InflationFetchError(
                f"Unexpected ECB unit '{source_unit}' for '{series_definition.series_code}'."
            )


def _build_index_records(
    series_definition: InflationSeriesDefinition,
    observations: List[ParsedObservation],
) -> List[InflationRecord]:
    return [
        InflationRecord(
            period=observation.period,
            index_value=observation.value,
            metadata=_record_metadata(series_definition, observation),
        )
        for observation in observations
    ]


def _record_metadata(
    series_definition: InflationSeriesDefinition,
    observation: ParsedObservation,
    extra: dict | None = None,
) -> dict:
    row = observation.row
    metadata = {
        "series_code": series_definition.series_code,
        "observation_kind": series_definition.observation_kind,
        "legend": row.get("LEGEND"),
        "status": row.get("OBS_STATUS"),
        "trend": row.get("TREND_INDICATOR"),
        "source_series": row.get("SERIES"),
        "source_unit": row.get("UNIT"),
        "valid_from": row.get("VALID_FROM"),
    }
    if extra:
        metadata.update(extra)
    return metadata


def _normalize_payload(payload) -> List[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "results", "records", "series", "observations"):
            value = payload.get(key)
            if isinstance(value, Iterable):
                return list(value)
    raise InflationFetchError("Unsupported payload structure from inflation API.")
