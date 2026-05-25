# Generated migration for missing Course fields

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_alter_course_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='performance_target',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='course',
            name='gad_themes',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='course',
            name='grading_system',
            field=models.TextField(blank=True),
        ),
    ]