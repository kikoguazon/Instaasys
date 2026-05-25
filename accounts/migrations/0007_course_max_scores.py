from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_course_grading_weights'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='quiz_max_scores',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='course',
            name='requirement_max',
            field=models.PositiveSmallIntegerField(default=100),
        ),
        migrations.AddField(
            model_name='course',
            name='midterm_max',
            field=models.PositiveSmallIntegerField(default=100),
        ),
        migrations.AddField(
            model_name='course',
            name='final_max',
            field=models.PositiveSmallIntegerField(default=100),
        ),
    ]
