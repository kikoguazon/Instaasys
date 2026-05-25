from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0009_course_program'),
    ]

    operations = [
        migrations.CreateModel(
            name='SystemLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('action', models.CharField(
                    choices=[
                        ('login', 'Login'),
                        ('logout', 'Logout'),
                        ('login_failed', 'Failed Login'),
                        ('create_student', 'Student Created'),
                        ('create_instructor', 'Instructor Created'),
                        ('create_admin', 'Admin Created'),
                        ('edit_user', 'User Edited'),
                        ('delete_user', 'User Deleted'),
                        ('create_course', 'Course Created'),
                        ('delete_course', 'Course Deleted'),
                        ('grade_update', 'Grades Updated'),
                        ('enrollment_update', 'Enrollment Updated'),
                        ('attendance', 'Attendance Recorded'),
                        ('password_change', 'Password Changed'),
                        ('syllabus_upload', 'Syllabus Uploaded'),
                    ],
                    max_length=30,
                )),
                ('target', models.CharField(blank=True, max_length=200)),
                ('detail', models.TextField(blank=True)),
                ('ip_address', models.GenericIPAddressField(blank=True, null=True)),
                ('timestamp', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='activity_logs',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-timestamp'],
            },
        ),
    ]
