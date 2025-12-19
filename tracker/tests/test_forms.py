from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from tracker.forms import SalaryEntryForm
from tracker.models import SalaryEntry


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
