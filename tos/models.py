from django.db import models


class TableOfSpecifications(models.Model):
    STATUS_CHOICES = [('pending', 'Generating…'), ('ready', 'Ready'), ('failed', 'Failed')]

    course      = models.ForeignKey('accounts.Course', on_delete=models.CASCADE,
                                    related_name='tos_list')
    exam_type   = models.CharField(max_length=50)
    total_items = models.IntegerField(default=50)
    topics_data   = models.JSONField(default=list)           # [{name, hours}, ...]
    weeks_covered = models.JSONField(default=list)           # [1, 2, 3, ...]
    tos_data      = models.JSONField(null=True, blank=True)  # full computed TOS
    xlsx_file   = models.FileField(upload_to='tos/', blank=True)
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                   default='pending')
    error_msg   = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Table of Specifications'
        verbose_name_plural = 'Tables of Specifications'

    def __str__(self):
        return f"{self.course.code} — {self.exam_type} TOS"
