from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase, override_settings
from django.urls import reverse


class RegistrationToggleTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="existing@example.com", password="pass12345")

    def test_register_disabled_redirects_to_login(self):
        response = self.client.get(reverse("register"))
        expected_url = response.wsgi_request.build_absolute_uri(reverse("login"))
        self.assertRedirects(response, expected_url, fetch_redirect_response=False)
        messages = [message.message for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("disabled" in msg.lower() for msg in messages))

    @override_settings(ALLOW_SELF_REGISTRATION=True)
    def test_register_enabled_renders_form(self):
        response = self.client.get(reverse("register"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create your account")

    def test_login_template_hides_register_link_when_disabled(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Create one")

    @override_settings(ALLOW_SELF_REGISTRATION=True)
    def test_login_template_shows_register_link_when_enabled(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Create one")
