from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

import requests
from django.test import TestCase

from tracker.inflation import InflationFetchError, fetch_inflation_series
from tracker.models import InflationSourceChoices


class InflationFetchTests(TestCase):
    @patch("tracker.inflation.requests.get")
    def test_fetch_inflation_series_parses_records(self, mock_get):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = [
            {
                "PERIOD": "2024-02-01",
                "OBS": "101.00",
                "UNIT": "IX",
                "SERIES": "HICP.M.DE.N.000000.4D0.INX",
            },
            {
                "PERIOD": "2024-01-01",
                "OBS": "100.50",
                "UNIT": "IX",
                "SERIES": "HICP.M.DE.N.000000.4D0.INX",
            },
            {
                "PERIOD": "2024-03-01",
                "OBS": "101.25",
                "UNIT": "IX",
                "SERIES": "HICP.M.DE.N.000000.4D0.INX",
            },
        ]
        mock_get.return_value = mock_response

        records = fetch_inflation_series(InflationSourceChoices.ECB_GERMANY)

        self.assertEqual(len(records), 3)
        self.assertEqual(records[0].period, date(2024, 1, 1))
        self.assertEqual(records[0].index_value, Decimal("100.50"))
        self.assertEqual(records[1].index_value, Decimal("101.00"))
        self.assertEqual(records[2].index_value, Decimal("101.25"))
        self.assertEqual(records[1].metadata["observation_kind"], "index")
        self.assertEqual(records[1].metadata["source_unit"], "IX")
        requested_url = mock_get.call_args[0][0]
        self.assertIn("HICP.M.DE.N.000000.4D0.INX", requested_url)

    @patch("tracker.inflation.requests.get")
    def test_fetch_inflation_series_accepts_wrapped_payload(self, mock_get):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "data": [
                {
                    "PERIOD": "2024-01-01",
                    "OBS_VALUE_AS_IS": "100.70",
                    "UNIT": "IX",
                    "SERIES": "HICP.M.DE.N.000000.4D0.INX",
                },
                {
                    "PERIOD": "2024-02-01",
                    "OBS_VALUE_ENTITY": "101.30",
                    "UNIT": "IX",
                    "SERIES": "HICP.M.DE.N.000000.4D0.INX",
                },
            ]
        }
        mock_get.return_value = mock_response

        records = fetch_inflation_series(InflationSourceChoices.ECB_GERMANY)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].index_value, Decimal("100.70"))
        self.assertEqual(records[1].index_value, Decimal("101.30"))

    @patch("tracker.inflation.requests.get")
    def test_fetch_inflation_series_rejects_unexpected_ecb_unit(self, mock_get):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = [
            {
                "PERIOD": "2024-01-01",
                "OBS": "2.0",
                "UNIT": "PCCH",
                "SERIES": "HICP.M.DE.N.000000.4D0.INX",
            }
        ]
        mock_get.return_value = mock_response

        with self.assertRaisesMessage(InflationFetchError, "Unexpected ECB unit"):
            fetch_inflation_series(InflationSourceChoices.ECB_GERMANY)

    @patch("tracker.inflation.requests.get")
    def test_fetch_inflation_series_rejects_unsupported_payload(self, mock_get):
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"unexpected": {"PERIOD": "2024-01-01", "OBS": "1.0"}}
        mock_get.return_value = mock_response

        with self.assertRaisesMessage(InflationFetchError, "Unsupported payload structure"):
            fetch_inflation_series(InflationSourceChoices.ECB_GERMANY)

    @patch("tracker.inflation.requests.get")
    def test_fetch_inflation_series_wraps_request_failures(self, mock_get):
        mock_get.side_effect = requests.RequestException("network unavailable")

        with self.assertRaisesMessage(InflationFetchError, "Failed to reach ECB data service"):
            fetch_inflation_series(InflationSourceChoices.ECB_GERMANY)

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
        self.assertEqual(latest.metadata["source_unit"], "IX")
