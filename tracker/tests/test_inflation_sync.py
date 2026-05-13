from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from tracker.inflation import InflationFetchError, InflationRecord, get_inflation_series_definition
from tracker.inflation_sync import (
    ensure_recent_inflation_data,
    refresh_inflation_source,
    source_has_current_series,
)
from tracker.models import InflationRate, InflationSource, InflationSourceChoices


class InflationSyncTests(TestCase):
    def setUp(self):
        self.source = InflationSource.objects.create(
            code=InflationSourceChoices.ECB_GERMANY,
            label="ECB Germany",
            description="",
            is_active=True,
            available_to_users=False,
        )
        self.series_code = get_inflation_series_definition(self.source.code).series_code

    @patch("tracker.inflation_sync.fetch_inflation_series")
    def test_refresh_inflation_source_upserts_records(self, mock_fetch):
        InflationRate.objects.create(
            source=self.source,
            period=date(2023, 12, 1),
            index_value=Decimal("99.0"),
        )
        InflationRate.objects.create(
            source=self.source,
            period=date(2024, 1, 1),
            index_value=Decimal("99.5"),
        )
        mock_fetch.return_value = [
            InflationRecord(period=date(2024, 1, 1), index_value=Decimal("100.0"), metadata={}),
            InflationRecord(period=date(2024, 2, 1), index_value=Decimal("101.0"), metadata={}),
        ]

        result = refresh_inflation_source(self.source)

        self.assertEqual(result.created_count, 1)
        self.assertEqual(result.updated_count, 1)
        self.assertEqual(self.source.rates.count(), 2)
        self.assertFalse(self.source.rates.filter(period=date(2023, 12, 1)).exists())
        self.assertEqual(
            self.source.rates.get(period=date(2024, 1, 1)).index_value,
            Decimal("100.0000"),
        )
        self.source.refresh_from_db()
        self.assertTrue(self.source.available_to_users)

    @patch("tracker.inflation_sync.fetch_inflation_series")
    def test_refresh_inflation_source_rejects_suspiciously_small_replacement(self, mock_fetch):
        for month in range(1, 11):
            InflationRate.objects.create(
                source=self.source,
                period=date(2024, month, 1),
                index_value=Decimal("100.0") + month,
                metadata={"series_code": self.series_code},
            )
        mock_fetch.return_value = [
            InflationRecord(
                period=date(2024, 10, 1),
                index_value=Decimal("110.0"),
                metadata={"series_code": self.series_code},
            )
        ]

        with self.assertRaisesMessage(InflationFetchError, "Refusing to replace 10 stored inflation rows"):
            refresh_inflation_source(self.source)

        self.assertEqual(self.source.rates.count(), 10)
        self.assertTrue(self.source.rates.filter(period=date(2024, 1, 1)).exists())

    @patch("tracker.inflation_sync.fetch_inflation_series")
    def test_refresh_inflation_source_rejects_duplicate_periods(self, mock_fetch):
        mock_fetch.return_value = [
            InflationRecord(period=date(2024, 1, 1), index_value=Decimal("100.0"), metadata={}),
            InflationRecord(period=date(2024, 1, 1), index_value=Decimal("101.0"), metadata={}),
        ]

        with self.assertRaisesMessage(InflationFetchError, "duplicate periods"):
            refresh_inflation_source(self.source)

        self.assertEqual(self.source.rates.count(), 0)

    @patch("tracker.inflation_sync.get_last_month_start")
    @patch("tracker.inflation_sync.fetch_inflation_series")
    def test_ensure_recent_inflation_data_refreshes_stale_sources(self, mock_fetch, mock_last_month):
        InflationRate.objects.create(
            source=self.source,
            period=date(2024, 1, 1),
            index_value=Decimal("100.0"),
        )
        mock_last_month.return_value = date(2024, 2, 1)
        mock_fetch.return_value = [
            InflationRecord(period=date(2024, 2, 1), index_value=Decimal("101.0"), metadata={})
        ]

        refreshed = ensure_recent_inflation_data()

        self.assertEqual(refreshed, 1)
        self.assertTrue(
            InflationRate.objects.filter(source=self.source, period=date(2024, 2, 1)).exists()
        )

    @patch("tracker.inflation_sync.get_last_month_start")
    @patch("tracker.inflation_sync.fetch_inflation_series")
    def test_ensure_recent_inflation_data_skips_fresh_sources(self, mock_fetch, mock_last_month):
        InflationRate.objects.create(
            source=self.source,
            period=date(2024, 2, 1),
            index_value=Decimal("101.0"),
            metadata={"series_code": self.series_code},
        )
        mock_last_month.return_value = date(2024, 2, 1)

        refreshed = ensure_recent_inflation_data()

        self.assertEqual(refreshed, 0)
        mock_fetch.assert_not_called()

    @patch("tracker.inflation_sync.get_last_month_start")
    @patch("tracker.inflation_sync.fetch_inflation_series")
    def test_ensure_recent_inflation_data_refreshes_obsolete_series(self, mock_fetch, mock_last_month):
        InflationRate.objects.create(
            source=self.source,
            period=date(2024, 2, 1),
            index_value=Decimal("101.0"),
            metadata={"series_code": "ICP.M.DE.N.000000.4.INX"},
        )
        mock_last_month.return_value = date(2024, 2, 1)
        mock_fetch.return_value = [
            InflationRecord(
                period=date(2024, 2, 1),
                index_value=Decimal("100.0"),
                metadata={"series_code": self.series_code},
            )
        ]

        refreshed = ensure_recent_inflation_data()

        self.assertEqual(refreshed, 1)
        self.assertEqual(
            self.source.rates.get(period=date(2024, 2, 1)).metadata["series_code"],
            self.series_code,
        )

    def test_source_has_current_series_requires_all_rows_to_match_configured_series(self):
        InflationRate.objects.create(
            source=self.source,
            period=date(2024, 1, 1),
            index_value=Decimal("100.0"),
            metadata={"series_code": self.series_code},
        )
        self.assertTrue(source_has_current_series(self.source))

        InflationRate.objects.create(
            source=self.source,
            period=date(2024, 2, 1),
            index_value=Decimal("101.0"),
            metadata={},
        )

        self.assertFalse(source_has_current_series(self.source))
