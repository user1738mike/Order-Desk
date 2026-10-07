from getpass import getpass

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from apps.accounts.managers import canonical_email
from apps.accounts.models import User


class Command(BaseCommand):
    help = "Interactively create one ordinary local-development account."

    def handle(self, *args, **options) -> None:
        if not settings.DEBUG:
            raise CommandError("This command is available only in local development.")
        try:
            email = canonical_email(input("Local account email: "))
            password = getpass("Password (hidden): ")
            if password != getpass("Confirm password (hidden): "):
                raise CommandError("Passwords did not match.")
            user = User(email=email, is_staff=False, is_superuser=False)
            validate_password(password, user=user)
            user.set_password(password)
            del password
            user.full_clean()
            with transaction.atomic():
                user.save()
        except ValidationError as error:
            raise CommandError(" ".join(error.messages)) from error
        except IntegrityError as error:
            raise CommandError(
                "The account could not be created; check for duplicates."
            ) from error
        except (EOFError, KeyboardInterrupt) as error:
            raise CommandError("Account creation cancelled.") from error
        self.stdout.write(self.style.SUCCESS("Ordinary local account created."))
