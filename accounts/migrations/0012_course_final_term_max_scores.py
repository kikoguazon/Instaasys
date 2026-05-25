from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_course_pt_max_scores'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='final_cs_max_scores',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='course',
            name='final_pt_max_scores',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='course',
            name='final_exam_max',
            field=models.PositiveSmallIntegerField(default=100),
        ),
    ]
