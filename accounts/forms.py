from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import User


class RegistrationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("email",)

    email = forms.EmailField(max_length=254, widget=forms.EmailInput(attrs={"autofocus": True}))
