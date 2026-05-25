from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('grading', '0003_graderecord_quiz_column_names'),
    ]

    operations = [
        migrations.AddField(
            model_name='graderecord',
            name='performance_task_scores',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='graderecord',
            name='pt_column_names',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
