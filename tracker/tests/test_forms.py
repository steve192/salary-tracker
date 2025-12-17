from django.contrib.auth import get_user_model
from django.test import TestCase

from tracker.forms import SalaryEntryForm
from tracker.models import Employer, SalaryEntry


class SalaryEntryFormTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="formuser@example.com", password="pass12345")

    def _base_payload(self):
        return {
            "entry_type": SalaryEntry.EntryType.REGULAR,
            "effective_date": "2024-01-01",
            "end_date": "",
            "amount": "5000",
            "notes": "",
            "employer_name": "Acme",
        }

    def test_creates_employer_when_name_unknown(self):
        form = SalaryEntryForm(data=self._base_payload(), user=self.user)
        self.assertTrue(form.is_valid(), form.errors)

        entry = form.save(commit=False)
        entry.user = self.user
        entry.save()
        self.assertEqual(entry.employer.name, "Acme")
        self.assertEqual(Employer.objects.filter(user=self.user).count(), 1)
        self.assertTrue(form.created_employer)

    def test_reuses_existing_employer_case_insensitive(self):
        employer = Employer.objects.create(user=self.user, name="Acme")
        payload = self._base_payload()
        payload["employer_name"] = "acme"

        form = SalaryEntryForm(data=payload, user=self.user)
        self.assertTrue(form.is_valid(), form.errors)

        entry = form.save(commit=False)
        entry.user = self.user
        entry.save()
        self.assertEqual(entry.employer, employer)
        self.assertEqual(Employer.objects.filter(user=self.user).count(), 1)
        self.assertFalse(form.created_employer)