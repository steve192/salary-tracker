from django.contrib import admin

from .models import Employer, InflationRate, SalaryEntry, UserPreference


@admin.register(Employer)
class EmployerAdmin(admin.ModelAdmin):
    list_display = ("name", "user")
    search_fields = ("name",)
    list_filter = ("user",)


@admin.register(SalaryEntry)
class SalaryEntryAdmin(admin.ModelAdmin):
    list_display = ("employer", "entry_type", "amount", "effective_date", "end_date", "user")
    list_filter = ("entry_type", "employer")
    search_fields = ("employer__name", "notes")


@admin.register(UserPreference)
class UserPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "currency")
    list_filter = ("currency",)


@admin.register(InflationRate)
class InflationRateAdmin(admin.ModelAdmin):
    list_display = ("source", "period", "index_value", "fetched_at")
    list_filter = ("source",)
    search_fields = ("source__label",)
    ordering = ("-period",)
