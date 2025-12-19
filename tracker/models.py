from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class CurrencyChoices(models.TextChoices):
    USD = "USD", "USD"
    EUR = "EUR", "EUR"
    GBP = "GBP", "GBP"
    CHF = "CHF", "CHF"
    CAD = "CAD", "CAD"


class Employer(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="employers")
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "name")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class SalaryEntry(models.Model):
    class EntryType(models.TextChoices):
        REGULAR = "REGULAR", "Regular"
        BONUS = "BONUS", "Bonus"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="salary_entries")
    employer = models.ForeignKey(Employer, on_delete=models.CASCADE, related_name="salary_entries")
    effective_date = models.DateField()
    end_date = models.DateField(blank=True, null=True)
    entry_type = models.CharField(max_length=10, choices=EntryType.choices, default=EntryType.REGULAR)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-effective_date", "-created_at"]

    def clean(self):
        if self.end_date and self.end_date < self.effective_date:
            raise ValidationError("End date must be on or after the effective date.")
        if self.entry_type == self.EntryType.BONUS and not self.end_date:
            raise ValidationError("Bonus entries require an end date so they can be amortized.")

    @property
    def is_active(self) -> bool:
        today = date.today()
        if self.end_date:
            return self.effective_date <= today <= self.end_date
        return self.effective_date <= today

    def __str__(self) -> str:
        return f"{self.employer.name} - {self.entry_type}"


class UserPreference(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="preferences")
    currency = models.CharField(max_length=3, choices=CurrencyChoices.choices, default=CurrencyChoices.USD)

    class InflationBaselineMode(models.TextChoices):
        GLOBAL = "GLOBAL", "Whole history"
        PER_EMPLOYER = "PER_EMPLOYER", "Current employer only"
        LAST_INCREASE = "LAST_INCREASE", "Last salary increase"
        MANUAL = "MANUAL", "Manual selection"

    inflation_baseline_mode = models.CharField(
        max_length=20,
        choices=InflationBaselineMode.choices,
        default=InflationBaselineMode.GLOBAL,
    )
    inflation_manual_entry = models.ForeignKey(
        "SalaryEntry",
        on_delete=models.SET_NULL,
        related_name="+",
        null=True,
        blank=True,
    )

    inflation_source = models.ForeignKey(
        "InflationSource",
        on_delete=models.SET_NULL,
        related_name="user_preferences",
        null=True,
        blank=True,
    )

    is_onboarded = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"Preferences for {self.user.email}"


class InflationSourceChoices(models.TextChoices):
    ECB_AUSTRIA = "ECB_AT", "Austria (ECB)"
    ECB_BELGIUM = "ECB_BE", "Belgium (ECB)"
    ECB_BULGARIA = "ECB_BG", "Bulgaria (ECB)"
    ECB_CROATIA = "ECB_HR", "Croatia (ECB)"
    ECB_CYPRUS = "ECB_CY", "Cyprus (ECB)"
    ECB_CZECHIA = "ECB_CZ", "Czechia (ECB)"
    ECB_DENMARK = "ECB_DK", "Denmark (ECB)"
    ECB_ESTONIA = "ECB_EE", "Estonia (ECB)"
    ECB_FINLAND = "ECB_FI", "Finland (ECB)"
    ECB_FRANCE = "ECB_FR", "France (ECB)"
    ECB_GERMANY = "ECB_DE", "Germany (ECB)"
    ECB_GREECE = "ECB_GR", "Greece (ECB)"
    ECB_HUNGARY = "ECB_HU", "Hungary (ECB)"
    ECB_IRELAND = "ECB_IE", "Ireland (ECB)"
    ECB_ITALY = "ECB_IT", "Italy (ECB)"
    ECB_LATVIA = "ECB_LV", "Latvia (ECB)"
    ECB_LITHUANIA = "ECB_LT", "Lithuania (ECB)"
    ECB_LUXEMBOURG = "ECB_LU", "Luxembourg (ECB)"
    ECB_MALTA = "ECB_MT", "Malta (ECB)"
    ECB_NETHERLANDS = "ECB_NL", "Netherlands (ECB)"
    ECB_POLAND = "ECB_PL", "Poland (ECB)"
    ECB_PORTUGAL = "ECB_PT", "Portugal (ECB)"
    ECB_ROMANIA = "ECB_RO", "Romania (ECB)"
    ECB_SLOVAKIA = "ECB_SK", "Slovakia (ECB)"
    ECB_SLOVENIA = "ECB_SI", "Slovenia (ECB)"
    ECB_SPAIN = "ECB_ES", "Spain (ECB)"
    ECB_SWEDEN = "ECB_SE", "Sweden (ECB)"


class InflationSource(models.Model):
    code = models.CharField(max_length=20, choices=InflationSourceChoices.choices, unique=True)
    label = models.CharField(max_length=100)
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)
    available_to_users = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["label"]

    def __str__(self) -> str:
        return self.label


class InflationRate(models.Model):
    source = models.ForeignKey(InflationSource, on_delete=models.CASCADE, related_name="rates")
    period = models.DateField(help_text="Month this rate applies to (1st of month)")
    index_value = models.DecimalField(max_digits=10, decimal_places=4)
    metadata = models.JSONField(blank=True, default=dict)
    fetched_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ("source", "period")
        ordering = ["-period"]

    def __str__(self) -> str:
        return f"{self.source.label} – {self.period:%b %Y}"
