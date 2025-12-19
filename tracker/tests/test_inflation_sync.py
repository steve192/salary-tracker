from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase

from tracker.inflation import InflationRecord
from tracker.inflation_sync import ensure_recent_inflation_data, refresh_inflation_source
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

    @patch("tracker.inflation_sync.fetch_inflation_series")
    def test_refresh_inflation_source_upserts_records(self, mock_fetch):
        mock_fetch.return_value = [
            InflationRecord(period=date(2024, 1, 1), index_value=Decimal("100.0"), metadata={}),
        ]

        result = refresh_inflation_source(self.source)

        self.assertEqual(result.created_count, 1)
        self.assertTrue(self.source.rates.filter(period=date(2024, 1, 1)).exists())
        self.source.refresh_from_db()
        self.assertTrue(self.source.available_to_users)

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
        )
        mock_last_month.return_value = date(2024, 2, 1)

        refreshed = ensure_recent_inflation_data()

        self.assertEqual(refreshed, 0)
        mock_fetch.assert_not_called()
