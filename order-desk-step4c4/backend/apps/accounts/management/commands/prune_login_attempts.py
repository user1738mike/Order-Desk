from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.accounts.login_limits import BUCKET_RETENTION
from apps.accounts.models import LoginAttemptBucket


class Command(BaseCommand):
    help = "Delete login attempt counters whose windows started over a day ago."

    def handle(self, *args, **options) -> None:
        count, _ = LoginAttemptBucket.objects.filter(
            window_started_at__lt=timezone.now() - BUCKET_RETENTION
        ).delete()
        self.stdout.write(f"Deleted {count} expired login attempt counters.")
