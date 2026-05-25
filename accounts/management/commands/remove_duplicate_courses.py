from django.core.management.base import BaseCommand
from django.db.models import Count
from accounts.models import Course


class Command(BaseCommand):
    help = 'Remove duplicate courses (same instructor + code + semester + school_year), keeping the oldest.'

    def handle(self, *args, **options):
        duplicates = (
            Course.objects
            .exclude(code='')
            .values('instructor', 'code', 'semester', 'school_year')
            .annotate(count=Count('id'))
            .filter(count__gt=1)
        )

        if not duplicates:
            self.stdout.write(self.style.SUCCESS('No duplicate courses found.'))
            return

        deleted_total = 0
        for dup in duplicates:
            courses = Course.objects.filter(
                instructor_id=dup['instructor'],
                code=dup['code'],
                semester=dup['semester'],
                school_year=dup['school_year'],
            ).order_by('created_at')

            keep = courses.first()
            to_delete = courses.exclude(pk=keep.pk)
            count = to_delete.count()
            to_delete.delete()
            deleted_total += count

            self.stdout.write(
                self.style.WARNING(
                    f'  Kept pk={keep.pk} ({keep.code} {keep.semester} {keep.school_year}), '
                    f'deleted {count} duplicate(s).'
                )
            )

        self.stdout.write(self.style.SUCCESS(f'Done. Total duplicates removed: {deleted_total}'))
