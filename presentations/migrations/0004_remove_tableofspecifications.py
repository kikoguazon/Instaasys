# Migration to remove TableOfSpecifications from presentations app
# as it has been moved to the tos app

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('presentations', '0003_alter_lessonplan_status'),
        ('tos', '0001_initial'),  # Ensure tos app is created first
    ]

    operations = [
        migrations.DeleteModel(
            name='TableOfSpecifications',
        ),
    ]
