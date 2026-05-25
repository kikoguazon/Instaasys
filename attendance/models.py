from django.db import models


class AttendanceSession(models.Model):
    """A single class session (date) for a course."""
    course = models.ForeignKey(
        'accounts.Course', on_delete=models.CASCADE,
        related_name='attendance_sessions'
    )
    date       = models.DateField()
    time_start = models.TimeField(null=True, blank=True)
    time_end   = models.TimeField(null=True, blank=True)
    notes      = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']
        unique_together = ('course', 'date')

    def __str__(self):
        return f"{self.course.code} — {self.date}"

    @property
    def present_count(self):
        return self.records.filter(status='present').count()

    @property
    def absent_count(self):
        return self.records.filter(status='absent').count()

    @property
    def late_count(self):
        return self.records.filter(status='late').count()

    @property
    def excused_count(self):
        return self.records.filter(status='excused').count()


class AttendanceRecord(models.Model):
    STATUS_CHOICES = [
        ('present', 'Present'),
        ('absent',  'Absent'),
        ('late',    'Late'),
        ('excused', 'Excused'),
    ]

    session    = models.ForeignKey(
        AttendanceSession, on_delete=models.CASCADE,
        related_name='records'
    )
    enrollment = models.ForeignKey(
        'accounts.Enrollment', on_delete=models.CASCADE,
        related_name='attendance_records'
    )
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='present'
    )

    class Meta:
        ordering = ['enrollment__student__last_name']
        unique_together = ('session', 'enrollment')

    def __str__(self):
        return f"{self.enrollment.student} — {self.session.date} — {self.status}"
