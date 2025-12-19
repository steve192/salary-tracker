from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import TestCase

from tracker.inflation import InflationFetchError, fetch_inflation_series
from tracker.models import InflationSourceChoices


class InflationFetchTests(TestCase):
    @patch("tracker.inflation.requests.get")
    def test_fetch_inflation_series_parses_records(self, mock_get):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = [
            {"PERIOD": "2024-01-01", "OBS": "100.0"},
            {"PERIOD": "2024-02-01", "OBS": "100.5"},
        ]
        mock_get.return_value = mock_response

        records = fetch_inflation_series(InflationSourceChoices.ECB_GERMANY)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].period, date(2024, 1, 1))
        self.assertEqual(records[1].index_value, Decimal("100.5"))
        self.assertIn("series_code", records[0].metadata)
        requested_url = mock_get.call_args[0][0]
        self.assertIn("ICP.M.DE.N.000000.4.INX", requested_url)

    def test_fetch_inflation_series_rejects_unknown_source(self):
        with self.assertRaises(InflationFetchError):
            fetch_inflation_series("ECB_UNKNOWN")


class InflationIntegrationTests(TestCase):
    def test_live_ecb_endpoint_is_parseable(self):
        records = fetch_inflation_series(InflationSourceChoices.ECB_GERMANY)
        self.assertGreater(len(records), 0, "Expected ECB feed to return at least one record.")
        latest = records[-1]
        self.assertIsInstance(latest.period, date)
        self.assertIsInstance(latest.index_value, Decimal)
        self.assertIn("series_code", latest.metadata)
