from django.contrib import messages
from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import FormView

from tracker.models import UserPreference

from .forms import RegistrationForm


User = get_user_model()


class RegisterView(FormView):
    template_name = "registration/register.html"
    form_class = RegistrationForm
    success_url = reverse_lazy("onboarding")

    def dispatch(self, request, *args, **kwargs):
        if settings.DESKTOP_MODE:
            return redirect("dashboard")
        if not settings.ALLOW_SELF_REGISTRATION:
            messages.error(request, "Self-service registration is disabled by the administrator.")
            return redirect("login")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save()
        UserPreference.objects.get_or_create(user=user)
        login(self.request, user)
        messages.success(self.request, "Welcome! Start by adding your preferences.")
        return super().form_valid(form)


class InitialSetupView(FormView):
    template_name = "registration/initial_setup.html"
    form_class = RegistrationForm
    success_url = reverse_lazy("onboarding")

    def dispatch(self, request, *args, **kwargs):
        if settings.DESKTOP_MODE:
            return redirect("dashboard")
        if User.objects.exists():
            return redirect("login")
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.save(commit=False)
        user.is_admin = True
        user.is_staff = True
        user.is_superuser = True
        user.save()
        UserPreference.objects.get_or_create(user=user)
        login(self.request, user)
        messages.success(self.request, "Administrator account created. Finish setup by choosing your preferences.")
        return super().form_valid(form)
