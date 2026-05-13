from datetime import datetime, timezone as datetime_timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.http import HttpResponse
from django.test import SimpleTestCase

from salary_tracker.middleware import AutomatedInflationSyncMiddleware


class AutomatedInflationSyncMiddlewareTests(SimpleTestCase):
    def _middleware(self):
        return AutomatedInflationSyncMiddleware(lambda request: HttpResponse("ok"))

    @patch("salary_tracker.middleware.ensure_recent_inflation_data")
    @patch("salary_tracker.middleware.timezone")
    def test_runs_sync_once_per_day(self, mock_timezone, mock_sync):
        middleware = self._middleware()
        request = SimpleNamespace()
        mock_timezone.now.return_value = datetime(2024, 1, 2, tzinfo=datetime_timezone.utc)

        middleware(request)
        middleware(request)

        self.assertEqual(mock_sync.call_count, 1)

        mock_timezone.now.return_value = datetime(2024, 1, 3, tzinfo=datetime_timezone.utc)
        middleware(request)

        self.assertEqual(mock_sync.call_count, 2)

    @patch("salary_tracker.middleware.logger")
    @patch("salary_tracker.middleware.ensure_recent_inflation_data")
    @patch("salary_tracker.middleware.timezone")
    def test_sync_failure_is_logged_and_request_continues(self, mock_timezone, mock_sync, mock_logger):
        middleware = self._middleware()
        mock_timezone.now.return_value = datetime(2024, 1, 2, tzinfo=datetime_timezone.utc)
        mock_sync.side_effect = RuntimeError("boom")

        response = middleware(SimpleNamespace())

        self.assertEqual(response.status_code, 200)
        mock_logger.exception.assert_called_once_with("Automated inflation refresh failed")
