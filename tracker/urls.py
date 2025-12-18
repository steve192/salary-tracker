from django.urls import path

from .views import (
    AdminPortalView,
    DashboardView,
    PreferenceOnboardingView,
    SettingsView,
    SalaryTimelineApiView,
    create_employer,
    create_salary_entry,
    delete_account,
    delete_employer,
    delete_salary_entry,
    select_inflation_baseline,
    update_preferences,
)

urlpatterns = [
    path("", DashboardView.as_view(), name="dashboard"),
    path("settings/", SettingsView.as_view(), name="settings"),
    path("onboarding/", PreferenceOnboardingView.as_view(), name="onboarding"),
    path("admin/", AdminPortalView.as_view(), name="admin-portal"),
    path("employers/create/", create_employer, name="employer-create"),
    path("employers/<int:pk>/delete/", delete_employer, name="employer-delete"),
    path("entries/create/", create_salary_entry, name="salary-entry-create"),
    path("entries/<int:pk>/delete/", delete_salary_entry, name="salary-entry-delete"),
    path("entries/<int:pk>/set-inflation-base/", select_inflation_baseline, name="salary-entry-set-inflation-base"),
    path("account/delete/", delete_account, name="account-delete"),
    path("preferences/", update_preferences, name="preferences"),
    path("api/salary-timeline/", SalaryTimelineApiView.as_view(), name="salary-timeline-api"),
]
