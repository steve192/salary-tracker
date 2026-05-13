from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from tracker.forms import EmployerForm, SalaryEntryForm, UserPreferenceForm
from tracker.models import Employer, InflationSource, InflationSourceChoices, SalaryEntry


class SalaryEntryFormTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="form@example.com", password="pass12345")

    def _form_data(self, **overrides):
        base = {
            "employer_name": "Acme",
            "entry_type": SalaryEntry.EntryType.REGULAR,
            "effective_date": "2024-01-01",
            "amount": "1000.00",
            "notes": "",
            "end_date": "",
        }
        base.update(overrides)
        return base

    def test_regular_entry_clears_end_date(self):
        form = SalaryEntryForm(data=self._form_data(end_date="2024-02-01"), user=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data["end_date"])

    def test_bonus_entry_defaults_end_date(self):
        form = SalaryEntryForm(
            data=self._form_data(entry_type=SalaryEntry.EntryType.BONUS),
            user=self.user,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["end_date"], date(2024, 12, 31))

    def test_bonus_requires_effective_date(self):
        form = SalaryEntryForm(
            data=self._form_data(entry_type=SalaryEntry.EntryType.BONUS, effective_date="", end_date=""),
            user=self.user,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("effective_date", form.errors)
        self.assertIn("end_date", form.errors)

    def test_amount_required(self):
        form = SalaryEntryForm(
            data=self._form_data(amount=""),
            user=self.user,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("amount", form.errors)


class EmployerFormTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="employer-form@example.com", password="pass12345")
        Employer.objects.create(user=self.user, name="Acme")

    def test_duplicate_employer_name_is_case_insensitive(self):
        form = EmployerForm(data={"name": " acme "}, user=self.user)

        self.assertFalse(form.is_valid())
        self.assertIn("name", form.errors)


class UserPreferenceFormTests(TestCase):
    def test_inflation_source_queryset_only_contains_available_active_sources(self):
        available = InflationSource.objects.create(
            code=InflationSourceChoices.ECB_GERMANY,
            label="Germany",
            available_to_users=True,
            is_active=True,
        )
        InflationSource.objects.create(
            code=InflationSourceChoices.ECB_FRANCE,
            label="France",
            available_to_users=False,
            is_active=True,
        )
        InflationSource.objects.create(
            code=InflationSourceChoices.ECB_ITALY,
            label="Italy",
            available_to_users=True,
            is_active=False,
        )

        form = UserPreferenceForm()

        self.assertEqual(list(form.fields["inflation_source"].queryset), [available])

    def test_required_source_is_relaxed_when_no_sources_are_available(self):
        form = UserPreferenceForm(require_source=True)

        self.assertFalse(form.fields["inflation_source"].required)
        self.assertEqual(
            form.fields["inflation_source"].help_text,
            "No shared inflation sources are available yet.",
        )
