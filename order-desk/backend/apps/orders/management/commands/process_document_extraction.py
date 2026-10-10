"""Shared CSV/text-PDF job lifecycle; no discovery or parallel queue."""

from apps.orders.management.commands.process_csv_extraction import Command as CSVCommand


class Command(CSVCommand):
    help = "Process one authorized CSV/text-PDF job, or reclaim its expired lease."
