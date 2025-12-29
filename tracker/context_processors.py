from django.conf import settings


def feature_flags(request):
    return {
        "allow_self_registration": getattr(settings, "ALLOW_SELF_REGISTRATION", False),
        "desktop_mode": getattr(settings, "DESKTOP_MODE", False),
    }
