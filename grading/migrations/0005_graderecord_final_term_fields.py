from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('grading', '0004_graderecord_performance_tasks'),
    ]

    operations = [
        migrations.AddField(
            model_name='graderecord',
            name='final_cs_scores',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='graderecord',
            name='final_cs_column_names',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='graderecord',
            name='final_pt_scores',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='graderecord',
            name='final_pt_column_names',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='graderecord',
            name='final_exam_score',
            field=models.FloatField(blank=True, null=True),
        ),
    ]
