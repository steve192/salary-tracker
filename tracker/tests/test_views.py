from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.urls import reverse

from tracker.inflation import InflationRecord
from tracker.models import Employer, InflationRate, InflationSource, InflationSourceChoices, SalaryEntry, UserPreference


User = get_user_model()
PROXYLESS_MIDDLEWARE = [mw for mw in settings.MIDDLEWARE if mw != "salary_tracker.middleware.ProxyPrefixMiddleware"]


@override_settings(FORCE_SCRIPT_NAME="", MIDDLEWARE=PROXYLESS_MIDDLEWARE)
class DashboardViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="dash@example.com", password="pass12345")
        self.client.force_login(self.user)
        employer = Employer.objects.create(user=self.user, name="Acme")
        SalaryEntry.objects.create(
            user=self.user,
            employer=employer,
            entry_type=SalaryEntry.EntryType.REGULAR,
            effective_date=date(2024, 1, 1),
            amount=Decimal("1000.00"),
        )
        prefs = UserPreference.objects.create(user=self.user)
        prefs.is_onboarded = True
        prefs.save(update_fields=["is_onboarded"])

    def test_dashboard_context_contains_timeline_and_forms(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("timeline", response.context)
        timeline = response.context["timeline"]
        self.assertGreater(len(timeline["labels"]), 0)
        self.assertIn("salary_form", response.context)
        self.assertIn("employer_summaries", response.context)


@override_settings(FORCE_SCRIPT_NAME="", MIDDLEWARE=PROXYLESS_MIDDLEWARE)
class AdminPortalViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="admin@example.com", password="pass12345", is_admin=True)
        self.client.force_login(self.user)
        self.source = InflationSource.objects.create(
            code=InflationSourceChoices.ECB_GERMANY,
            label="ECB Germany",
            description="",
            is_active=True,
            available_to_users=False,
        )
        prefs, _ = UserPreference.objects.get_or_create(user=self.user)
        prefs.is_onboarded = True
        prefs.save(update_fields=["is_onboarded"])

    @patch("tracker.views.fetch_inflation_series")
    def test_fetch_source_creates_rates_and_marks_available(self, mock_fetch):
        mock_fetch.return_value = [
            InflationRecord(period=date(2024, 1, 1), index_value=Decimal("100.0"), metadata={}),
            InflationRecord(period=date(2024, 2, 1), index_value=Decimal("101.0"), metadata={}),
        ]

        response = self.client.post(
            reverse("admin-portal"),
            {"action": "fetch-source", "source_id": self.source.id},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(InflationRate.objects.filter(source=self.source).count(), 2)
        self.source.refresh_from_db()
        self.assertTrue(self.source.available_to_users)
        msgs = [m.message for m in get_messages(response.wsgi_request)]
        self.assertTrue(any("new rows" in msg for msg in msgs))

    def test_toggle_source_availability(self):
        response = self.client.post(
            reverse("admin-portal"),
            {"action": "toggle-source-availability", "source_id": self.source.id},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.source.refresh_from_db()
        self.assertTrue(self.source.available_to_users)
        msgs = [m.level for m in get_messages(response.wsgi_request)]
        self.assertIn(messages.SUCCESS, msgs)


@override_settings(FORCE_SCRIPT_NAME="", MIDDLEWARE=PROXYLESS_MIDDLEWARE)
class EmployerViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="employer@example.com", password="pass12345")
        self.client.force_login(self.user)
        prefs = UserPreference.objects.create(user=self.user)
        prefs.is_onboarded = True
        prefs.save(update_fields=["is_onboarded"])

    def test_create_employer_endpoint(self):
        response = self.client.post(
            reverse("employer-create"),
            {"name": "Globex"},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Employer.objects.filter(user=self.user, name="Globex").exists())

    def test_delete_employer_endpoint(self):
        employer = Employer.objects.create(user=self.user, name="DeleteMe")
        response = self.client.post(reverse("employer-delete", args=[employer.id]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Employer.objects.filter(pk=employer.id).exists())


@override_settings(FORCE_SCRIPT_NAME="", MIDDLEWARE=PROXYLESS_MIDDLEWARE)
class ManualBaselineSelectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="manual@example.com", password="pass12345")
        self.client.force_login(self.user)
        self.employer = Employer.objects.create(user=self.user, name="Manual Inc")
        self.entry = SalaryEntry.objects.create(
            user=self.user,
            employer=self.employer,
            entry_type=SalaryEntry.EntryType.REGULAR,
            effective_date=date(2024, 1, 1),
            amount=Decimal("1000.00"),
        )
        self.preferences, _ = UserPreference.objects.get_or_create(user=self.user)
        self.preferences.is_onboarded = True
        self.preferences.save(update_fields=["is_onboarded"])

    def test_select_inflation_baseline_updates_preference(self):
        response = self.client.post(reverse("salary-entry-set-inflation-base", args=[self.entry.id]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.preferences.refresh_from_db()
        self.assertEqual(self.preferences.inflation_manual_entry, self.entry)

    def test_deleting_baseline_clears_preference(self):
        self.preferences.inflation_manual_entry = self.entry
        self.preferences.save(update_fields=["inflation_manual_entry"])
        response = self.client.post(reverse("salary-entry-delete", args=[self.entry.id]), follow=True)
        self.assertEqual(response.status_code, 200)
        self.preferences.refresh_from_db()
        self.assertIsNone(self.preferences.inflation_manual_entry)
