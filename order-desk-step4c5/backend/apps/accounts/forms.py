from django.contrib.auth.forms import UserChangeForm, UserCreationForm

from apps.accounts.models import User


class AccountCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("email",)


class AccountChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User
        fields = ("email", "first_name", "last_name", "is_active", "is_staff")
