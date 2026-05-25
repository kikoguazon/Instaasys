from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='TableOfSpecifications',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('exam_type', models.CharField(max_length=50)),
                ('total_items', models.IntegerField(default=50)),
                ('topics_data', models.JSONField(default=list)),
                ('tos_data', models.JSONField(blank=True, null=True)),
                ('xlsx_file', models.FileField(blank=True, upload_to='tos/')),
                ('status', models.CharField(choices=[('pending', 'Generating…'), ('ready', 'Ready'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('error_msg', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('course', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tos_list', to='accounts.course')),
            ],
            options={
                'verbose_name': 'Table of Specifications',
                'verbose_name_plural': 'Tables of Specifications',
                'ordering': ['-created_at'],
            },
        ),
    ]
