"""One explicit bounded job; direct restricted runtime credentials only."""

from uuid import UUID

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.orders.extraction_services import process_extraction


class Command(BaseCommand):
    help = "Process one authorized CSV job, or reclaim its expired lease."

    def add_arguments(self, parser):
        parser.add_argument("--workspace", type=UUID, required=True)
        parser.add_argument("--actor", type=UUID, required=True)
        parser.add_argument("--job", type=UUID, required=True)

    def handle(self, *args, **options):
        call_command("check_runtime_role", verbosity=0)
        try:
            workspace_id = UUID(str(options["workspace"]))
        except (ValueError, TypeError) as error:
            raise CommandError("A valid workspace UUID is required.") from error
        try:
            actor = User.objects.get(pk=options["actor"], is_active=True)
        except User.DoesNotExist as error:
            raise CommandError("An active authorized processor is required.") from error
        outcome = process_extraction(
            actor=actor, organization_id=workspace_id, job_id=options["job"]
        )
        self.stdout.write(f"Extraction job {options['job']}: {outcome}.")
