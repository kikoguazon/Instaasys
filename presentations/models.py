from django.db import models


class LessonPlan(models.Model):
    STATUS_PENDING  = 'pending'
    STATUS_BLUEPRINT_PENDING = 'blueprint_pending'
    STATUS_BLUEPRINT_APPROVED = 'blueprint_approved'
    STATUS_READY    = 'ready'
    STATUS_FAILED   = 'failed'
    STATUS_CHOICES  = [
        (STATUS_PENDING, 'Generating…'),
        (STATUS_BLUEPRINT_PENDING, 'Blueprint Ready for Review'),
        (STATUS_BLUEPRINT_APPROVED, 'Generating Presentation…'),
        (STATUS_READY,   'Ready'),
        (STATUS_FAILED,  'Failed'),
    ]

    course      = models.ForeignKey('accounts.Course', on_delete=models.CASCADE,
                                    related_name='lesson_plans')
    topic       = models.CharField(max_length=300)
    week_number = models.PositiveIntegerField(default=1)
    objectives  = models.TextField()
    ai_data     = models.JSONField(null=True, blank=True)   # raw AI output
    pptx_file   = models.FileField(upload_to='pptx/', blank=True)
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                   default=STATUS_PENDING)
    error_msg   = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'lessons_lessonplan'
        ordering = ['week_number', '-created_at']
        managed = False

    def __str__(self):
        return f"Week {self.week_number}: {self.topic}"