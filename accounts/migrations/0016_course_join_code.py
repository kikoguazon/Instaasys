import secrets
import string
from django.db import migrations, models


def backfill_join_codes(apps, schema_editor):
    Course = apps.get_model('accounts', 'Course')
    chars = string.ascii_uppercase + string.digits
    existing = set()
    for course in Course.objects.all():
        while True:
            code = ''.join(secrets.choice(chars) for _ in range(6))
            if code not in existing:
                existing.add(code)
                course.join_code = code
                course.save(update_fields=['join_code'])
                break


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0015_user_theme_preference'),
    ]

    operations = [
        # Step 1: add field nullable, no unique yet
        migrations.AddField(
            model_name='course',
            name='join_code',
            field=models.CharField(max_length=6, blank=True, null=True),
        ),
        # Step 2: backfill all rows with unique codes
        migrations.RunPython(backfill_join_codes, migrations.RunPython.noop),
        # Step 3: now enforce unique + index
        migrations.AlterField(
            model_name='course',
            name='join_code',
            field=models.CharField(max_length=6, unique=True, blank=True, db_index=True),
        ),
        # Enrollment flag
        migrations.AddField(
            model_name='enrollment',
            name='joined_via_code',
            field=models.BooleanField(default=False),
        ),
    ]
