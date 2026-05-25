from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_course_block_timeframe'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='program',
            field=models.CharField(
                blank=True,
                choices=[
                    ('IT', 'Information Technology'),
                    ('CS', 'Computer Science'),
                    ('CE', 'Computer Engineering'),
                ],
                max_length=10,
            ),
        ),
    ]
