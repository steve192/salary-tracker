import logging

from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max, Min
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import TemplateView, FormView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .forms import EmployerForm, SalaryEntryForm, UserPreferenceForm
from .inflation import InflationFetchError
from .inflation_sync import refresh_inflation_source
from .models import (
    Employer,
    InflationSource,
    InflationRate,
    InflationSourceChoices,
    SalaryEntry,
    UserPreference,
)


logger = logging.getLogger(__name__)
User = get_user_model()
from .services import (
    build_employer_compensation_summary,
    build_future_salary_targets,
    build_inflation_gap_report,
    build_salary_timeline,
)


class AdminRequiredMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_admin:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
def _redirect_with_next(request: HttpRequest, fallback_name: str) -> HttpResponse:
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect(fallback_name)


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "tracker/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        preferences = (
            UserPreference.objects.select_related("inflation_manual_entry", "inflation_manual_entry__employer")
            .filter(user=user)
            .first()
        )
        if not preferences:
            preferences = UserPreference.objects.create(user=user)
        employers_qs = Employer.objects.filter(user=user).order_by("name")
        employer_names = list(employers_qs.values_list("name", flat=True))
        employers = list(employers_qs)
        timeline_payload = build_salary_timeline(
            user,
            preferences.inflation_baseline_mode,
            preferences.inflation_source,
            preferences.inflation_manual_entry,
        )
        future_targets, future_targets_message, future_targets_period = build_future_salary_targets(user, preferences)
        context.update(
            {
                "salary_form": SalaryEntryForm(user=user),
                "current_currency": preferences.currency,
                "employers": employers,
                "employer_names": employer_names,
                "entries": SalaryEntry.objects.filter(user=user).select_related("employer"),
                "timeline": timeline_payload,
                "employer_summaries": build_employer_compensation_summary(user, employers, preferences, preferences.inflation_source),
                "baseline_mode": preferences.inflation_baseline_mode,
                "manual_baseline_entry": preferences.inflation_manual_entry,
                "today": timezone.now().date(),
                "future_salary_targets": future_targets,
                "future_salary_targets_message": future_targets_message,
                "future_salary_targets_period": future_targets_period,
            }
        )
        return context


class SettingsView(LoginRequiredMixin, TemplateView):
    template_name = "tracker/management.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        preferences, _ = UserPreference.objects.get_or_create(user=user)
        employers = (
            Employer.objects.filter(user=user)
            .annotate(entry_count=Count("salary_entries"))
            .order_by("name")
        )
        inflation_records = InflationRate.objects.select_related("source")
        summaries = []
        for source in InflationSource.objects.all().order_by("label"):
            qs = inflation_records.filter(source=source)
            if qs.exists():
                stats = qs.aggregate(start=Min("period"), end=Max("period"), count=Count("id"))
                summaries.append(
                    {
                        "source": source.label,
                        "start": stats["start"],
                        "end": stats["end"],
                        "count": stats["count"],
                        "latest_fetch": qs.order_by("-fetched_at").values_list("fetched_at", flat=True).first(),
                        "available": source.available_to_users,
                    }
                )
        inflation_gap_report = build_inflation_gap_report(user)
        context.update(
            {
                "preference_form": UserPreferenceForm(instance=preferences),
                "employer_form": EmployerForm(user=user),
                "employers": employers,
                "inflation_summaries": summaries,
                "inflation_gap_report": inflation_gap_report,
            }
        )
        return context


class PreferenceOnboardingView(LoginRequiredMixin, FormView):
    template_name = "tracker/onboarding.html"
    form_class = UserPreferenceForm
    success_url = reverse_lazy("dashboard")

    def dispatch(self, request, *args, **kwargs):
        self.preferences, _ = UserPreference.objects.get_or_create(user=request.user)
        if self.preferences.is_onboarded:
            return redirect("dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.preferences
        kwargs["require_source"] = True
        return kwargs

    def form_valid(self, form):
        preference = form.save(commit=False)
        preference.is_onboarded = True
        preference.save()
        messages.success(self.request, "Preferences saved. You're all set!")
        return super().form_valid(form)


class AdminPortalView(AdminRequiredMixin, TemplateView):
    template_name = "tracker/admin_portal.html"

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        handlers = {
            "fetch-source": self._handle_fetch_source,
            "create-source": self._handle_create_source,
            "toggle-source-availability": lambda req: self._handle_source_flag(req, "available_to_users"),
            "toggle-source-active": lambda req: self._handle_source_flag(req, "is_active"),
            "promote-user": lambda req: self._handle_user_admin(req, promote=True),
            "demote-user": lambda req: self._handle_user_admin(req, promote=False),
            "delete-user": self._handle_delete_user,
        }
        handler = handlers.get(action)
        if handler:
            return handler(request)
        messages.error(request, "Unsupported admin action.")
        return redirect("admin-portal")

    def _handle_fetch_source(self, request):
        source = self._get_source_or_message(request, request.POST.get("source_id"))
        if not source:
            return redirect("admin-portal")

        try:
            result = refresh_inflation_source(source)
        except InflationFetchError as exc:
            logger.exception("Inflation fetch failed for source %s", source.code)
            messages.error(request, f"Download failed: {exc}")
            return redirect("admin-portal")

        if not result.record_count:
            messages.warning(request, f"No data returned for {source.label}.")
            return redirect("admin-portal")

        messages.success(request, f"{source.label}: {result.created_count} new rows, {result.updated_count} updated.")
        return redirect("admin-portal")

    def _handle_create_source(self, request):
        code = request.POST.get("code")
        label = (request.POST.get("label") or "").strip()
        description = (request.POST.get("description") or "").strip()
        available = bool(request.POST.get("available_to_users"))

        valid_codes = {choice for choice, _ in InflationSourceChoices.choices}
        if code not in valid_codes:
            messages.error(request, "Select a supported source code.")
            return redirect("admin-portal")
        if not label:
            messages.error(request, "Provide a display label for the source.")
            return redirect("admin-portal")
        if InflationSource.objects.filter(code=code).exists():
            messages.info(request, "That source code already exists.")
            return redirect("admin-portal")

        source = InflationSource.objects.create(
            code=code,
            label=label,
            description=description,
            is_active=True,
            available_to_users=available,
        )
        try:
            result = refresh_inflation_source(source)
        except InflationFetchError as exc:
            logger.exception("Inflation fetch failed for new source %s", source.code)
            messages.warning(request, f"Source '{label}' added, but fetching data failed: {exc}")
            return redirect("admin-portal")

        if result.record_count:
            messages.success(
                request,
                f"Source '{label}' added and downloaded {result.created_count} new row{'s' if result.created_count != 1 else ''}.",
            )
        else:
            messages.warning(request, f"Source '{label}' added, but no data was returned by the provider.")
        return redirect("admin-portal")

    def _handle_source_flag(self, request, field_name: str):
        source = self._get_source_or_message(request, request.POST.get("source_id"))
        if not source:
            return redirect("admin-portal")
        current = getattr(source, field_name)
        new_value = not current
        setattr(source, field_name, new_value)
        source.save(update_fields=[field_name, "updated_at"])
        label = "available to users" if field_name == "available_to_users" else "active"
        state = "enabled" if new_value else "disabled"
        messages.success(request, f"{source.label} {label} state {state}.")
        return redirect("admin-portal")

    def _handle_user_admin(self, request, *, promote: bool):
        target = self._get_user_or_message(request, request.POST.get("user_id"))
        if not target:
            return redirect("admin-portal")

        if promote:
            if target.is_admin:
                messages.info(request, f"{target.email} is already an admin.")
                return redirect("admin-portal")
            target.is_admin = True
            target.save(update_fields=["is_admin"])
            messages.success(request, f"{target.email} promoted to admin.")
            return redirect("admin-portal")

        if target == request.user:
            messages.error(request, "You cannot remove your own admin access.")
            return redirect("admin-portal")
        if not target.is_admin:
            messages.info(request, f"{target.email} is not an admin.")
            return redirect("admin-portal")
        if User.objects.filter(is_admin=True).count() <= 1:
            messages.error(request, "At least one admin is required.")
            return redirect("admin-portal")
        target.is_admin = False
        target.save(update_fields=["is_admin"])
        messages.success(request, f"{target.email} demoted from admin.")
        return redirect("admin-portal")

    def _handle_delete_user(self, request):
        target = self._get_user_or_message(request, request.POST.get("user_id"))
        if not target:
            return redirect("admin-portal")
        if target == request.user:
            messages.error(request, "You cannot delete your own account.")
            return redirect("admin-portal")
        if target.is_admin and User.objects.filter(is_admin=True).count() <= 1:
            messages.error(request, "Cannot delete the last admin user.")
            return redirect("admin-portal")
        email = target.email
        target.delete()
        messages.success(request, f"User {email} deleted.")
        return redirect("admin-portal")

    def _get_source_or_message(self, request, source_id):
        if not source_id:
            messages.error(request, "Missing source identifier.")
            return None
        try:
            return InflationSource.objects.get(pk=source_id)
        except InflationSource.DoesNotExist:
            messages.error(request, "Inflation source not found.")
            return None

    def _get_user_or_message(self, request, user_id):
        if not user_id:
            messages.error(request, "Missing user identifier.")
            return None
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            messages.error(request, "User not found.")
            return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        users = (
            User.objects.annotate(
                employer_count=Count("employers"),
                entry_count=Count("salary_entries"),
            )
            .order_by("email")
        )
        source_rows = []
        for source in InflationSource.objects.all().order_by("label"):
            stats = source.rates.aggregate(start=Min("period"), end=Max("period"), count=Count("id"))
            source_rows.append(
                {
                    "obj": source,
                    "count": stats["count"],
                    "start": stats["start"],
                    "end": stats["end"],
                    "has_data": stats["count"] > 0,
                    "latest_fetch": source.rates.order_by("-fetched_at").values_list("fetched_at", flat=True).first(),
                    "available": source.available_to_users,
                    "active": source.is_active,
                }
            )

        existing_codes = set(InflationSource.objects.values_list("code", flat=True))
        available_choices = [
            {"code": value, "label": label}
            for value, label in InflationSourceChoices.choices
            if value not in existing_codes
        ]

        context.update(
            {
                "managed_users": users,
                "inflation_sources": source_rows,
                "admin_count": User.objects.filter(is_admin=True).count(),
                "source_choices": available_choices,
            }
        )
        return context


@login_required
def create_employer(request: HttpRequest) -> HttpResponse:
    form = EmployerForm(request.POST, user=request.user)
    if form.is_valid():
        employer = form.save(commit=False)
        employer.user = request.user
        employer.save()
        messages.success(request, f"Employer {employer.name} added.")
    else:
        messages.error(request, "Unable to save employer. Check the form inputs.")
    return _redirect_with_next(request, "dashboard")


@login_required
def delete_employer(request: HttpRequest, pk: int) -> HttpResponse:
    if request.method != "POST":
        return redirect("settings")
    employer = get_object_or_404(Employer, pk=pk, user=request.user)
    employer_name = employer.name
    deleted_entries = employer.salary_entries.count()
    employer.delete()
    if deleted_entries:
        messages.warning(request, f"Employer {employer_name} removed along with {deleted_entries} salary entr{'y' if deleted_entries == 1 else 'ies'}.")
    else:
        messages.info(request, f"Employer {employer_name} removed.")
    return _redirect_with_next(request, "settings")


@login_required
def create_salary_entry(request: HttpRequest) -> HttpResponse:
    form = SalaryEntryForm(request.POST, user=request.user)
    if form.is_valid():
        entry = form.save(commit=False)
        entry.user = request.user
        entry.save()
        if getattr(form, "created_employer", False):
            messages.info(request, f"New employer {entry.employer.name} created and linked to this entry.")
        messages.success(request, "Salary entry saved.")
    else:
        messages.error(request, "Could not save salary entry. Please fix the errors.")
    return redirect("dashboard")


@login_required
def delete_salary_entry(request: HttpRequest, pk: int) -> HttpResponse:
    entry = get_object_or_404(SalaryEntry, pk=pk, user=request.user)
    clearing_manual = False
    preferences = (
        UserPreference.objects.filter(user=request.user, inflation_manual_entry=entry).first()
        if entry.entry_type == SalaryEntry.EntryType.REGULAR
        else None
    )
    if preferences:
        preferences.inflation_manual_entry = None
        preferences.save(update_fields=["inflation_manual_entry"])
        clearing_manual = True
    entry.delete()
    if clearing_manual:
        messages.info(request, "Salary entry removed and manual inflation baseline cleared.")
    else:
        messages.info(request, "Salary entry removed.")
    return redirect("dashboard")


@login_required
def select_inflation_baseline(request: HttpRequest, pk: int) -> HttpResponse:
    if request.method != "POST":
        return redirect("dashboard")
    entry = get_object_or_404(
        SalaryEntry,
        pk=pk,
        user=request.user,
        entry_type=SalaryEntry.EntryType.REGULAR,
    )
    preferences, _ = UserPreference.objects.get_or_create(user=request.user)
    preferences.inflation_manual_entry = entry
    preferences.save(update_fields=["inflation_manual_entry"])
    if preferences.inflation_baseline_mode == UserPreference.InflationBaselineMode.MANUAL:
        messages.success(request, "Inflation baseline updated.")
    else:
        messages.info(request, "Manual inflation baseline selected. Switch to Manual selection mode to see it in the chart.")
    return redirect("dashboard")


@login_required
def update_preferences(request: HttpRequest) -> HttpResponse:
    preferences, _ = UserPreference.objects.get_or_create(user=request.user)
    form = UserPreferenceForm(request.POST, instance=preferences)
    if form.is_valid():
        form.save()
        messages.success(request, "Preferences updated.")
    else:
        messages.error(request, "Unable to update preferences.")
    return _redirect_with_next(request, "dashboard")


@login_required
def delete_account(request: HttpRequest) -> HttpResponse:
    if request.method != "POST":
        return redirect("settings")

    user = request.user
    if user.is_admin and User.objects.filter(is_admin=True).count() <= 1:
        messages.error(request, "You cannot delete the last administrator account.")
        return redirect("settings")

    email = user.email
    logout(request)
    user.delete()
    messages.success(request, f"Account {email} deleted. We're sorry to see you go.")
    return redirect("login")


class SalaryTimelineApiView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        payload = build_salary_timeline(request.user)
        return Response(payload)
