"""Create a synthetic workspace through the existing atomic domain service."""

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.managers import canonical_email
from apps.accounts.models import User
from apps.organizations.services import create_organization


class Command(BaseCommand):
    help = "Create one local workspace for an existing active account."

    def handle(self, *args, **options) -> None:
        if not settings.DEBUG:
            raise CommandError("This command is available only in local development.")
        try:
            email = canonical_email(input("Existing local account email: "))
            user = User.objects.filter(email=email, is_active=True).first()
            if user is None:
                raise CommandError("Select an active existing local account.")
            name = input("Synthetic workspace name: ")
            organization = create_organization(actor=user, name=name)
        except ValidationError as error:
            raise CommandError(" ".join(error.messages)) from error
        except PermissionDenied as error:
            raise CommandError("Select an active existing local account.") from error
        except (EOFError, KeyboardInterrupt) as error:
            raise CommandError("Workspace creation cancelled.") from error
        self.stdout.write(
            self.style.SUCCESS(f"Local workspace created: {organization.pk}")
        )
