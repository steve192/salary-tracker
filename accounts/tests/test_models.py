from django.contrib.auth import get_user_model
from django.test import TestCase


User = get_user_model()


class UserManagerTests(TestCase):
    def test_first_user_marked_admin(self):
        user = User.objects.create_user(email="first@example.com", password="pass12345")
        self.assertTrue(user.is_admin)
        self.assertFalse(user.is_staff)

    def test_additional_user_not_auto_admin(self):
        User.objects.create_user(email="first@example.com", password="pass12345")
        user = User.objects.create_user(email="second@example.com", password="pass12345")
        self.assertFalse(user.is_admin)

    def test_create_superuser_sets_required_flags(self):
        superuser = User.objects.create_superuser(email="admin@example.com", password="pass12345")
        self.assertTrue(superuser.is_admin)
        self.assertTrue(superuser.is_staff)
        self.assertTrue(superuser.is_superuser)

    def test_create_superuser_raises_when_flags_missing(self):
        with self.assertRaises(ValueError):
            User.objects.create_superuser(email="bad@example.com", password="pass12345", is_staff=False)
