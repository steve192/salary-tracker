from datetime import timedelta

from django import forms

from .models import Employer, InflationSource, SalaryEntry, UserPreference


class EmployerForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

    class Meta:
        model = Employer
        fields = ["name"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Acme Corp"}),
        }

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if self.user and Employer.objects.filter(user=self.user, name__iexact=name).exists():
            raise forms.ValidationError("You already added this employer.")
        return name


class SalaryEntryForm(forms.ModelForm):
    employer_name = forms.CharField(
        label="Employer",
        max_length=200,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Start typing to search or add",
                "autocomplete": "off",
                "list": "employer-options",
            }
        ),
    )

    class Meta:
        model = SalaryEntry
        fields = ["entry_type", "effective_date", "end_date", "amount", "notes"]
        widgets = {
            "effective_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        self.fields["end_date"].required = False
        self.fields["notes"].required = False
        if self.instance.pk and self.instance.employer:
            self.fields["employer_name"].initial = self.instance.employer.name
        self._employer_obj = None
        self.created_employer = False

    def clean_employer_name(self):
        name = self.cleaned_data["employer_name"].strip()
        if not name:
            raise forms.ValidationError("Employer name is required.")
        if not self.user:
            raise forms.ValidationError("Unable to determine the current user.")
        existing = Employer.objects.filter(user=self.user, name__iexact=name).first()
        if existing:
            self._employer_obj = existing
            self.created_employer = False
        else:
            self._employer_obj = Employer(user=self.user, name=name)
            self.created_employer = True
        return name

    def clean(self):
        cleaned_data = super().clean()
        entry_type = cleaned_data.get("entry_type")
        effective_date = cleaned_data.get("effective_date")
        end_date = cleaned_data.get("end_date")
        amount = cleaned_data.get("amount")

        if entry_type == SalaryEntry.EntryType.BONUS:
            if not effective_date:
                self.add_error("effective_date", "Start date is required for bonuses.")
            if not end_date and effective_date:
                try:
                    anniversary = effective_date.replace(year=effective_date.year + 1)
                except ValueError:
                    anniversary = effective_date + timedelta(days=365)
                cleaned_data["end_date"] = anniversary - timedelta(days=1)
                end_date = cleaned_data["end_date"]
            if not end_date:
                self.add_error("end_date", "End date is required for bonuses.")
            elif effective_date and end_date < effective_date:
                self.add_error("end_date", "End date cannot be before the start date.")
        else:
            cleaned_data["end_date"] = None

        if amount is None:
            self.add_error("amount", "Amount is required.")

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not self._employer_obj:
            raise ValueError("Employer must be set before saving the salary entry.")
        # If the employer is unsaved, persist it now.
        if self._employer_obj.pk is None:
            self._employer_obj.save()
        instance.employer = self._employer_obj
        if commit:
            instance.save()
        return instance


class UserPreferenceForm(forms.ModelForm):
    def __init__(self, *args, require_source: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        available_sources = InflationSource.objects.filter(is_active=True, available_to_users=True).order_by("label")
        self.fields["inflation_source"].queryset = available_sources
        self.fields["inflation_source"].required = require_source
        if not available_sources.exists():
            self.fields["inflation_source"].required = False
            self.fields["inflation_source"].help_text = "No shared inflation sources are available yet."
        elif require_source:
            self.fields["inflation_source"].help_text = "Pick one of the available centrally managed inflation feeds."

    class Meta:
        model = UserPreference
        fields = ["currency", "inflation_baseline_mode", "inflation_source"]
        widgets = {
            "inflation_baseline_mode": forms.Select(),
            "inflation_source": forms.Select(),
        }
