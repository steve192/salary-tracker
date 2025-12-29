import logging
import os

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.utils import timezone
from urllib.parse import urljoin

from django.http import HttpResponseRedirect
from django.urls import NoReverseMatch, reverse, get_script_prefix, set_script_prefix
from tracker.inflation_sync import ensure_recent_inflation_data


logger = logging.getLogger(__name__)


def _matches_prefix(path: str, prefix: str, script_name: str = "") -> bool:
    if not prefix:
        return False
    normalized = prefix if prefix.startswith("/") else f"/{prefix.lstrip('/')}"
    if script_name and normalized.startswith(script_name):
        normalized = normalized[len(script_name) :] or "/"
    return path.startswith(normalized)


def _clean_prefix(raw_prefix: str | None, *, strip_multi: bool = False) -> str:
    if not raw_prefix:
        return ""
    prefix = raw_prefix.strip()
    if not prefix:
        return ""
    if strip_multi and "," in prefix:
        prefix = prefix.split(",", 1)[0].strip()
    if prefix in {"", "/"}:
        return ""
    if not prefix.startswith("/"):
        prefix = "/" + prefix.lstrip("/")
    return prefix.rstrip("/")


def _strip_script_name(url: str, script_name: str) -> str:
    if script_name and url.startswith(script_name):
        stripped = url[len(script_name) :]
        return stripped or "/"
    return url


def _is_static_or_media(path: str, script_name: str) -> bool:
    static_url = settings.STATIC_URL or ""
    media_url = settings.MEDIA_URL or ""
    if _matches_prefix(path, static_url, script_name):
        return True
    if _matches_prefix(path, media_url, script_name):
        return True
    return False


def _ensure_desktop_user():
    user_model = get_user_model()
    preference_model = apps.get_model("tracker", "UserPreference")
    user = user_model.objects.order_by("id").first()
    if user:
        return user

    email = os.environ.get("DJANGO_DESKTOP_USER_EMAIL", "desktop@local")
    user = user_model.objects.create_user(
        email=email,
        is_admin=True,
        is_staff=True,
        is_superuser=True,
    )
    preference_model.objects.get_or_create(user=user)
    return user


class ProxyPrefixMiddleware:
    """Adjust incoming request paths when the app lives under a proxy prefix."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.forced_prefix = _clean_prefix(getattr(settings, "FORCE_SCRIPT_NAME", ""))

    def _current_prefix(self, request) -> str:
        header = request.META.get("HTTP_X_FORWARDED_PREFIX")
        header_prefix = _clean_prefix(header, strip_multi=True)
        chosen = self.forced_prefix or header_prefix
        logger.debug(
            "ProxyPrefixMiddleware prefix resolved forced=%s header=%s chosen=%s path=%s",
            self.forced_prefix,
            header_prefix,
            chosen,
            request.path,
        )
        return chosen

    def __call__(self, request):
        prefix = self._current_prefix(request)
        original_script_prefix = get_script_prefix()
        if prefix:
            request.META["SCRIPT_NAME"] = prefix
            if request.path.startswith(prefix):
                trimmed = request.path[len(prefix) :] or "/"
                logger.debug(
                    "ProxyPrefixMiddleware trimming path original=%s trimmed=%s script_name=%s",
                    request.path,
                    trimmed,
                    prefix,
                )
                request.path_info = trimmed
                request.path = trimmed
                request.META["PATH_INFO"] = trimmed
            set_script_prefix(f"{prefix}/")
            try:
                return self.get_response(request)
            finally:
                set_script_prefix(original_script_prefix)
        return self.get_response(request)


class InitialSetupMiddleware:
    """Force users through the initial setup screen until the first account exists."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.user_model = get_user_model()
        self._setup_complete = None

    def __call__(self, request):
        if settings.DESKTOP_MODE:
            if not self.user_model.objects.exists():
                _ensure_desktop_user()
            self._setup_complete = True
            return self.get_response(request)

        if self._setup_complete is True:
            return self.get_response(request)

        if not self.user_model.objects.exists():
            self._setup_complete = False
            if not self._is_allowed_path(request):
                setup_path = reverse("initial-setup")
                logger.debug(
                    "InitialSetupMiddleware redirecting requested=%s script_name=%s setup_path=%s",
                    request.path,
                    request.META.get("SCRIPT_NAME", ""),
                    setup_path,
                )
                return HttpResponseRedirect(setup_path)
        else:
            self._setup_complete = True

        return self.get_response(request)

    def _is_allowed_path(self, request):
        path = request.path
        script_name = request.META.get("SCRIPT_NAME", "")
        static_url = settings.STATIC_URL or ""
        media_url = settings.MEDIA_URL or ""
        if _matches_prefix(path, static_url, script_name):
            return True
        if _matches_prefix(path, media_url, script_name):
            return True
        try:
            setup_path = reverse("initial-setup")
        except NoReverseMatch:
            return True
        stripped_setup = _strip_script_name(setup_path, script_name)
        allowed = path == stripped_setup
        if not allowed:
            cleaned_static = _strip_script_name(static_url, script_name)
            cleaned_media = _strip_script_name(media_url, script_name)
            logger.debug(
                "InitialSetupMiddleware evaluating path=%s stripped_setup=%s script_name=%s static=%s media=%s",
                path,
                stripped_setup,
                script_name,
                cleaned_static,
                cleaned_media,
            )
        if not allowed:
            logger.debug(
                "InitialSetupMiddleware blocking requested=%s allowed=%s script_name=%s",
                path,
                stripped_setup,
                script_name,
            )
        return allowed


class OnboardingRequiredMiddleware:
    """Redirect authenticated users to onboarding until preferences are confirmed."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.preference_model = apps.get_model("tracker", "UserPreference")

    def __call__(self, request):
        if request.user.is_authenticated:
            preferences = getattr(request.user, "preferences", None)
            if preferences is None:
                preferences, _ = self.preference_model.objects.get_or_create(user=request.user)
            if not preferences.is_onboarded and not self._is_allowed_path(request):
                onboarding_path = reverse("onboarding")
                logger.debug(
                    "OnboardingRequiredMiddleware redirecting requested=%s script_name=%s onboarding_path=%s",
                    request.path,
                    request.META.get("SCRIPT_NAME", ""),
                    onboarding_path,
                )
                return HttpResponseRedirect(onboarding_path)
        return self.get_response(request)

    def _is_allowed_path(self, request):
        path = request.path
        script_name = request.META.get("SCRIPT_NAME", "")
        static_url = settings.STATIC_URL or ""
        media_url = settings.MEDIA_URL or ""
        if _matches_prefix(path, static_url, script_name):
            return True
        if _matches_prefix(path, media_url, script_name):
            return True
        allow_names = ["onboarding", "logout", "account-delete"]
        for name in allow_names:
            try:
                allowed_path = _strip_script_name(reverse(name), script_name)
                if path == allowed_path:
                    return True
            except NoReverseMatch:
                continue
        logger.debug(
            "OnboardingRequiredMiddleware blocking path requested=%s script_name=%s",
            path,
            script_name,
        )
        return False


class DesktopAutoLoginMiddleware:
    """Automatically authenticate a single local user in desktop mode."""

    def __init__(self, get_response):
        self.get_response = get_response
        self._desktop_user_id = None

    def __call__(self, request):
        if not settings.DESKTOP_MODE:
            return self.get_response(request)

        if request.user.is_authenticated:
            return self.get_response(request)

        if _is_static_or_media(request.path, request.META.get("SCRIPT_NAME", "")):
            return self.get_response(request)

        user = self._get_or_create_user()
        backend = settings.AUTHENTICATION_BACKENDS[0]
        login(request, user, backend=backend)
        return self.get_response(request)

    def _get_or_create_user(self):
        if self._desktop_user_id:
            user_model = get_user_model()
            try:
                return user_model.objects.get(pk=self._desktop_user_id)
            except user_model.DoesNotExist:
                self._desktop_user_id = None
        user = _ensure_desktop_user()
        self._desktop_user_id = user.pk
        return user


class AbsoluteRedirectMiddleware:
    """Ensure redirect responses carry absolute URLs so upstream proxies won't rewrite paths."""

    REDIRECT_STATUSES = {301, 302, 303, 307, 308}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        location = response.get("Location")
        if not location or response.status_code not in self.REDIRECT_STATUSES:
            return response
        if location.startswith("http://") or location.startswith("https://"):
            return response
        if location.startswith("//"):
            return response
        base = request.build_absolute_uri()
        if location.startswith("/"):
            absolute = request.build_absolute_uri(location)
        else:
            absolute = urljoin(base, location)
        response["Location"] = absolute
        return response


class AutomatedInflationSyncMiddleware:
    """Runs the inflation freshness check once per process each day."""

    def __init__(self, get_response):
        self.get_response = get_response
        self._last_check_date = None

    def __call__(self, request):
        self._maybe_run_automatic_sync()
        return self.get_response(request)

    def _maybe_run_automatic_sync(self):
        today = timezone.now().date()
        if self._last_check_date == today:
            return
        try:
            ensure_recent_inflation_data(logger)
        except Exception:
            logger.exception("Automated inflation refresh failed")
        finally:
            self._last_check_date = today
