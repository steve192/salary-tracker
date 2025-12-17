from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from tracker.models import Employer, SalaryEntry


class SalaryEntryModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="tester@example.com", password="pass12345")
        self.employer = Employer.objects.create(user=self.user, name="Acme Corp")

    def test_regular_entry_requires_end_date_not_before_start(self):
        entry = SalaryEntry(
            user=self.user,
            employer=self.employer,
            entry_type=SalaryEntry.EntryType.REGULAR,
            effective_date=date(2024, 1, 1),
            end_date=date(2023, 12, 31),
            amount=Decimal("1000.00"),
        )

        with self.assertRaises(ValidationError) as exc:
            entry.full_clean()

        self.assertIn("End date must be on or after the effective date", str(exc.exception))

    def test_bonus_entry_requires_end_date(self):
        entry = SalaryEntry(
            user=self.user,
            employer=self.employer,
            entry_type=SalaryEntry.EntryType.BONUS,
            effective_date=date(2024, 1, 1),
            amount=Decimal("500.00"),
        )

        with self.assertRaises(ValidationError) as exc:
            entry.full_clean()

        self.assertIn("Bonus entries require an end date", str(exc.exception))
