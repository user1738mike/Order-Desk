"""Bounded credential input and an explicit representation of the caller."""

from rest_framework import serializers

from apps.accounts.models import User


class PasswordField(serializers.CharField):
    def to_internal_value(self, data: object) -> str:
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = PasswordField(max_length=1024, trim_whitespace=False, write_only=True)

    def validate_email(self, value: str) -> str:
        return value.lower()


class SessionUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("id", "email")
        read_only_fields = fields
