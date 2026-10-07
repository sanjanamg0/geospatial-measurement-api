from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from measurements.models import UploadedFile


class Command(BaseCommand):
    help = "Delete uploaded files (record, features and stored upload) older than --days."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30, help="Retention period in days")
        parser.add_argument("--dry-run", action="store_true", help="Only report what would go")

    def handle(self, *args, days, dry_run, **options):
        cutoff = timezone.now() - timedelta(days=days)
        old = UploadedFile.objects.filter(created_at__lt=cutoff)
        count = old.count()
        if dry_run:
            self.stdout.write(f"{count} file(s) older than {days} days would be deleted.")
            return
        for record in old:
            record.upload_path().unlink(missing_ok=True)
            record.delete()
        self.stdout.write(f"Deleted {count} file(s) older than {days} days.")
