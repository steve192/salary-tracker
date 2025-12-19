from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from tracker.models import (
    Employer,
    InflationRate,
    InflationSource,
    InflationSourceChoices,
    SalaryEntry,
    UserPreference,
)
from tracker.services import (
    build_employer_compensation_summary,
    build_future_salary_targets,
    build_inflation_gap_report,
    build_salary_timeline,
)


class BuildSalaryTimelineTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="timeline@example.com", password="pass12345")
        self.employer = Employer.objects.create(user=self.user, name="Globex")
        self.source = InflationSource.objects.create(
            code=InflationSourceChoices.ECB_GERMANY,
            label="ECB Germany",
            description="",
            available_to_users=True,
        )
        self.preferences = UserPreference.objects.create(user=self.user, inflation_source=self.source)

    def test_empty_payload_when_no_entries(self):
        payload = build_salary_timeline(self.user, self.preferences.inflation_baseline_mode, self.source)

        self.assertEqual(payload["labels"], [])
        self.assertEqual(payload["inflationMeta"]["reason"], "missing-timeline")
        self.assertFalse(payload["inflationMeta"]["ready"])

    def test_regular_and_bonus_entries_reflected_in_timeline(self):
        SalaryEntry.objects.create(
            user=self.user,
            employer=self.employer,
            entry_type=SalaryEntry.EntryType.REGULAR,
            effective_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
            amount=Decimal("1000.00"),
        )
        SalaryEntry.objects.create(
            user=self.user,
            employer=self.employer,
            entry_type=SalaryEntry.EntryType.BONUS,
            effective_date=date(2024, 3, 1),
            end_date=date(2024, 5, 31),
            amount=Decimal("600.00"),
        )

        for month_offset in range(6):
            month = month_offset + 1
            InflationRate.objects.create(
                source=self.source,
                period=date(2024, month, 1),
                index_value=Decimal("100.0") + Decimal(str(month_offset)),
            )

        payload = build_salary_timeline(self.user, UserPreference.InflationBaselineMode.GLOBAL, self.source)

        self.assertEqual(payload["labels"][0], "Jan 2024")
        self.assertEqual(payload["labels"][-1], "Jun 2024")
        self.assertEqual(payload["baseSeries"], [1000.0] * 6)
        self.assertEqual(payload["totalSeries"][0], 1000.0)
        self.assertEqual(payload["totalSeries"][2], 1200.0)
        self.assertEqual(payload["totalSeries"][3], 1200.0)
        self.assertEqual(payload["totalSeries"][4], 1200.0)

        self.assertTrue(all(value is not None for value in payload["inflationSeries"]))
        self.assertTrue(payload["inflationMeta"]["ready"])
        self.assertEqual(payload["inflationMeta"]["baseSalary"], 1000.0)

        self.assertEqual(len(payload["bonusWindows"]), 1)
        window = payload["bonusWindows"][0]
        self.assertEqual(window["start"], "2024-03-01")
        self.assertEqual(window["end"], "2024-05-31")
        self.assertEqual(
            payload["employerSwitches"],
            [{"label": "Jan 2024", "employer": "Globex"}],
        )

    def test_last_increase_mode_targets_latest_raise(self):
        first_entry = SalaryEntry.objects.create(
            user=self.user,
            employer=self.employer,
            entry_type=SalaryEntry.EntryType.REGULAR,
            effective_date=date(2023, 1, 1),
            end_date=date(2023, 12, 31),
            amount=Decimal("800.00"),
        )
        second_entry = SalaryEntry.objects.create(
            user=self.user,
            employer=self.employer,
            entry_type=SalaryEntry.EntryType.REGULAR,
            effective_date=date(2024, 6, 1),
            end_date=date(2024, 12, 31),
            amount=Decimal("1400.00"),
        )
        self.assertIsNotNone(first_entry)
        self.assertIsNotNone(second_entry)
        for year in (2023, 2024):
            for month in range(1, 13):
                InflationRate.objects.create(
                    source=self.source,
                    period=date(year, month, 1),
                    index_value=Decimal("100.0") + Decimal(str((year - 2023) * 12 + month)),
                )

        payload = build_salary_timeline(
            self.user,
            UserPreference.InflationBaselineMode.LAST_INCREASE,
            self.source,
        )
        meta = payload["inflationMeta"]
        self.assertEqual(meta["mode"], UserPreference.InflationBaselineMode.LAST_INCREASE)
        self.assertIsNone(meta["baseLabel"])
        self.assertIsNone(meta["baseSalary"])
        self.assertTrue(all(value is not None for value in payload["inflationSeries"]))

        jan_index = payload["labels"].index("Jan 2023")
        jun_index = payload["labels"].index("Jun 2024")
        self.assertEqual(payload["inflationSeries"][jan_index], float(first_entry.amount))
        self.assertEqual(payload["inflationSeries"][jun_index], float(second_entry.amount))

    def test_manual_mode_requires_selection(self):
        base_entry = SalaryEntry.objects.create(
            user=self.user,
            employer=self.employer,
            entry_type=SalaryEntry.EntryType.REGULAR,
            effective_date=date(2024, 3, 1),
            end_date=date(2024, 5, 31),
            amount=Decimal("1250.00"),
        )
        SalaryEntry.objects.create(
            user=self.user,
            employer=self.employer,
            entry_type=SalaryEntry.EntryType.REGULAR,
            effective_date=date(2024, 6, 1),
            end_date=date(2024, 8, 31),
            amount=Decimal("1500.00"),
        )
        for month_offset in range(1, 9):
            InflationRate.objects.create(
                source=self.source,
                period=date(2024, month_offset, 1),
                index_value=Decimal("100.0") + Decimal(str(month_offset)),
            )

        payload = build_salary_timeline(
            self.user,
            UserPreference.InflationBaselineMode.MANUAL,
            self.source,
            manual_entry=base_entry,
        )
        meta = payload["inflationMeta"]
        self.assertTrue(meta["ready"])
        self.assertEqual(meta["manualEntryId"], base_entry.id)
        self.assertEqual(meta["baseLabel"], "Mar 2024")
        empty_months = [value for idx, value in enumerate(payload["inflationSeries"]) if payload["labels"][idx] in {"Jan 2024", "Feb 2024"}]
        self.assertTrue(all(value is None for value in empty_months))

        payload_missing = build_salary_timeline(
            self.user,
            UserPreference.InflationBaselineMode.MANUAL,
            self.source,
        )
        self.assertEqual(payload_missing["inflationMeta"]["reason"], "manual-baseline-unset")

class EmployerCompensationSummaryTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="summary@example.com", password="pass12345")
        self.employer = Employer.objects.create(user=self.user, name="Initech")
        self.source = InflationSource.objects.create(
            code=InflationSourceChoices.ECB_GERMANY,
            label="ECB Germany",
            description="",
            available_to_users=True,
            is_active=True,
        )
        self.preferences = UserPreference.objects.create(user=self.user)

    def _seed_rates(self):
        for month in range(1, 7):
            InflationRate.objects.create(
                source=self.source,
                period=date(2024, month, 1),
                index_value=Decimal("100.0") + Decimal(str(month - 1)),
            )

    def test_summary_with_inflation_source_computes_delta(self):
        self._seed_rates()
        SalaryEntry.objects.create(
            user=self.user,
            employer=self.employer,
            entry_type=SalaryEntry.EntryType.REGULAR,
            effective_date=date(2024, 1, 1),
            end_date=date(2024, 6, 30),
            amount=Decimal("1000.00"),
        )

        self.preferences.inflation_source = self.source
        self.preferences.save()

        summaries = build_employer_compensation_summary(
            self.user,
            employers=[self.employer],
            preferences=self.preferences,
            inflation_source=self.source,
        )

        self.assertEqual(len(summaries), 1)
        summary = summaries[0]
        self.assertTrue(summary.inflation_ready)
        self.assertIsNotNone(summary.inflation_total)
        self.assertIsNotNone(summary.delta_amount)
        self.assertIn(summary.delta_state, {"gain", "loss", "even"})
        self.assertGreater(len(summary.monthly_breakdown), 0)
        self.assertTrue(any(month.delta is not None for month in summary.monthly_breakdown))
        self.assertIsNotNone(summary.monthly_breakdown[-1].cumulative_delta)

    def test_summary_without_source_flags_reason(self):
        SalaryEntry.objects.create(
            user=self.user,
            employer=self.employer,
            entry_type=SalaryEntry.EntryType.REGULAR,
            effective_date=date(2024, 1, 1),
            amount=Decimal("1000.00"),
        )
        summaries = build_employer_compensation_summary(
            self.user,
            employers=[self.employer],
            preferences=self.preferences,
            inflation_source=None,
        )

        self.assertFalse(summaries[0].inflation_ready)
        self.assertEqual(
            summaries[0].inflation_message,
            "Select an inflation source in Settings to enable this comparison.",
        )


class InflationGapReportTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="gap@example.com", password="pass12345")
        self.employer = Employer.objects.create(user=self.user, name="Gap Inc")
        self.source = InflationSource.objects.create(
            code=InflationSourceChoices.ECB_GERMANY,
            label="ECB Germany",
            description="",
            available_to_users=True,
            is_active=True,
        )
        SalaryEntry.objects.create(
            user=self.user,
            employer=self.employer,
            entry_type=SalaryEntry.EntryType.REGULAR,
            effective_date=date(2024, 1, 1),
            end_date=date(2024, 3, 31),
            amount=Decimal("1000.00"),
        )

    def test_reports_missing_months_when_rates_incomplete(self):
        InflationRate.objects.create(source=self.source, period=date(2024, 1, 1), index_value=Decimal("100.0"))
        # Intentionally skip February, add March to create a gap.
        InflationRate.objects.create(source=self.source, period=date(2024, 3, 1), index_value=Decimal("102.0"))

        report = build_inflation_gap_report(self.user)

        self.assertTrue(report["has_salary_data"])
        self.assertGreater(len(report["sources"]), 0)
        source_report = report["sources"][0]
        self.assertEqual(source_report.source, self.source.code)
        self.assertFalse(source_report.is_complete)
        self.assertGreater(source_report.missing_months, 0)
        self.assertGreater(len(source_report.missing_ranges), 0)


class FutureSalaryTargetsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="future@example.com", password="pass12345")
        self.employer = Employer.objects.create(user=self.user, name="Future Co")
        self.source = InflationSource.objects.create(
            code=InflationSourceChoices.ECB_GERMANY,
            label="ECB Germany",
            description="",
            available_to_users=True,
            is_active=True,
        )
        self.preferences = UserPreference.objects.create(user=self.user, inflation_source=self.source)
        self.first_entry = SalaryEntry.objects.create(
            user=self.user,
            employer=self.employer,
            entry_type=SalaryEntry.EntryType.REGULAR,
            effective_date=date(2023, 1, 1),
            amount=Decimal("1000.00"),
        )
        self.current_entry = SalaryEntry.objects.create(
            user=self.user,
            employer=self.employer,
            entry_type=SalaryEntry.EntryType.REGULAR,
            effective_date=date(2024, 1, 1),
            amount=Decimal("1500.00"),
        )

    def _seed_rates(self):
        InflationRate.objects.create(source=self.source, period=date(2023, 1, 1), index_value=Decimal("100.0"))
        InflationRate.objects.create(source=self.source, period=date(2024, 1, 1), index_value=Decimal("108.0"))
        InflationRate.objects.create(source=self.source, period=date(2024, 3, 1), index_value=Decimal("110.0"))

    def test_missing_source_returns_message(self):
        self.preferences.inflation_source = None
        self.preferences.save(update_fields=["inflation_source"])

        targets, message, period = build_future_salary_targets(self.user, preferences=self.preferences)

        self.assertEqual(targets, [])
        self.assertIsNotNone(message)
        self.assertIsNone(period)

    def test_targets_include_last_raise_and_employer_start(self):
        self._seed_rates()

        targets, message, period = build_future_salary_targets(self.user, preferences=self.preferences)

        self.assertIsNone(message)
        self.assertEqual(period, date(2024, 3, 1))
        self.assertGreaterEqual(len(targets), 2)
        target_map = {target.key: target for target in targets}
        self.assertIn("last-raise", target_map)
        self.assertIn("employer-start", target_map)
        last_raise = target_map["last-raise"]
        self.assertIsNone(last_raise.reason)
        self.assertGreater(last_raise.target_salary, self.current_entry.amount)
        self.assertEqual(
            last_raise.delta_amount,
            (last_raise.target_salary - self.current_entry.amount).quantize(Decimal("0.01")),
        )

    def test_manual_baseline_target_appears_when_preference_set(self):
        self._seed_rates()
        self.preferences.inflation_manual_entry = self.first_entry
        self.preferences.save(update_fields=["inflation_manual_entry"])

        targets, message, _ = build_future_salary_targets(self.user, preferences=self.preferences)

        target_map = {target.key: target for target in targets}
        self.assertIn("manual-baseline", target_map)
        self.assertIsNone(target_map["manual-baseline"].reason)
