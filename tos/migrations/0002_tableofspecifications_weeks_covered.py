from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tos', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='tableofspecifications',
            name='weeks_covered',
            field=models.JSONField(default=list),
        ),
    ]
