import os

from django.core.management.base import BaseCommand

from accounts.models import User
from tracker.models import UserPreference


class Command(BaseCommand):
    help = "Create an initial user defined via environment variables"

    def handle(self, *args, **options):
        email = os.environ.get("INITIAL_USER_EMAIL")
        password = os.environ.get("INITIAL_USER_PASSWORD")
        if not email or not password:
            self.stdout.write(self.style.WARNING("INITIAL_USER_EMAIL/PASSWORD not set. Skipping user bootstrap."))
            return

        if User.objects.filter(email=email).exists():
            self.stdout.write(self.style.SUCCESS(f"User {email} already exists."))
            return

        user = User.objects.create_user(email=email, password=password)
        UserPreference.objects.get_or_create(user=user)
        self.stdout.write(self.style.SUCCESS(f"Initial user {email} created."))
