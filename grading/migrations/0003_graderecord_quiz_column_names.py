# Generated migration

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('grading', '0002_alter_graderecord_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='graderecord',
            name='quiz_column_names',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
