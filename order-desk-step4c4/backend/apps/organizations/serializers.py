"""Public workspace fields. Memberships and account details stay internal."""

from rest_framework import serializers

from apps.organizations.models import MembershipRole, Organization


class WorkspaceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ("id", "name")
        read_only_fields = fields


class WorkspaceIdField(serializers.UUIDField):
    def to_internal_value(self, data):
        # JSON UUIDs must be strings; reject bool/int values rather than letting
        # UUIDField reinterpret an integer as a different identifier.
        if not isinstance(data, str):
            self.fail("invalid")
        return super().to_internal_value(data)


class WorkspaceSelectionSerializer(serializers.Serializer):
    workspace_id = WorkspaceIdField()

    def validate(self, attrs):
        unexpected = set(self.initial_data) - set(self.fields)
        if unexpected:
            raise serializers.ValidationError(
                {field: ["Unknown field."] for field in sorted(unexpected)}
            )
        return attrs


class WorkspaceContextSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="organization_id", read_only=True)
    name = serializers.CharField(source="organization_name", read_only=True)
    role = serializers.ChoiceField(choices=MembershipRole.choices, read_only=True)
