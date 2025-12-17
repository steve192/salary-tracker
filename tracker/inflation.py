from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from decimal import Decimal
from typing import Iterable, List

import requests

from .models import InflationSourceChoices

ECB_GERMANY_ENDPOINT = "https://data.ecb.europa.eu/data-detail-api/ICP.M.DE.N.000000.4.INX"


class InflationFetchError(Exception):
    """Raised when an inflation feed cannot be fetched or parsed."""


@dataclass
class InflationRecord:
    period: date
    index_value: Decimal
    metadata: dict


def fetch_inflation_series(source: str) -> List[InflationRecord]:
    if source == InflationSourceChoices.ECB_GERMANY:
        return _fetch_ecb_germany()
    raise InflationFetchError("Unsupported inflation source.")


def _fetch_ecb_germany() -> List[InflationRecord]:
    try:
        response = requests.get(ECB_GERMANY_ENDPOINT, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise InflationFetchError("Failed to reach ECB data service.") from exc

    payload = response.json()
    rows = _normalize_payload(payload)
    if not rows:
        raise InflationFetchError("ECB service returned no data.")

    records: List[InflationRecord] = []
    for row in rows:
        period_str = row.get("PERIOD") or row.get("period")
        index_raw = row.get("OBS") or row.get("OBS_VALUE_AS_IS") or row.get("OBS_VALUE_ENTITY")
        if not period_str or index_raw is None:
            continue
        try:
            period = datetime.strptime(period_str, "%Y-%m-%d").date()
        except ValueError as exc:
            raise InflationFetchError(f"Invalid period value '{period_str}'.") from exc
        index_str = str(index_raw).strip()
        if not index_str or index_str == "-":
            # Skip incomplete rows without a numeric index.
            continue
        try:
            index_value = Decimal(index_str)
        except Exception as exc:  # noqa: BLE001
            raise InflationFetchError(f"Invalid index value '{index_raw}'.") from exc

        records.append(
            InflationRecord(
                period=period,
                index_value=index_value,
                metadata={
                    "legend": row.get("LEGEND"),
                    "status": row.get("OBS_STATUS"),
                    "trend": row.get("TREND_INDICATOR"),
                    "source_series": row.get("SERIES"),
                    "valid_from": row.get("VALID_FROM"),
                },
            )
        )

    records.sort(key=lambda r: r.period)
    return records


def _normalize_payload(payload) -> List[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "results", "records", "series", "observations"):
            value = payload.get(key)
            if isinstance(value, Iterable):
                return list(value)
    raise InflationFetchError("Unsupported payload structure from inflation API.")
