from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0010_systemlog'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='pt_max_scores',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AlterField(
            model_name='course',
            name='requirement_max',
            field=models.PositiveSmallIntegerField(default=10),
        ),
    ]
