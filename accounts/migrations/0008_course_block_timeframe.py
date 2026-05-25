from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_course_max_scores'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='block',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='course',
            name='time_frame',
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
