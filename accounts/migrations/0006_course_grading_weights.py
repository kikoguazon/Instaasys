from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_add_missing_course_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='cs_weight',
            field=models.PositiveSmallIntegerField(default=20),
        ),
        migrations.AddField(
            model_name='course',
            name='req_weight',
            field=models.PositiveSmallIntegerField(default=40),
        ),
        migrations.AddField(
            model_name='course',
            name='exam_weight',
            field=models.PositiveSmallIntegerField(default=40),
        ),
    ]
