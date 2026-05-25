from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('assessments', '0004_questionset_question_question_set'),
    ]

    operations = [
        migrations.AlterField(
            model_name='question',
            name='topic',
            field=models.TextField(),
        ),
    ]
