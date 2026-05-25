from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tos', '0002_tableofspecifications_weeks_covered'),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS lessons_tableofspecifications;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
