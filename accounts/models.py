import secrets
import string
from django.contrib.auth.models import AbstractUser
from django.db import models


def _generate_join_code():
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(secrets.choice(chars) for _ in range(6))
        if not Course.objects.filter(join_code=code).exists():
            return code


class User(AbstractUser):
    ROLE_INSTRUCTOR = 'instructor'
    ROLE_STUDENT = 'student'
    ROLE_CHOICES = [
        (ROLE_INSTRUCTOR, 'Instructor'),
        (ROLE_STUDENT, 'Student'),
    ]
    THEME_LIGHT = 'light'
    THEME_DARK = 'dark'
    THEME_SYSTEM = 'system'
    THEME_CHOICES = [
        (THEME_LIGHT, 'Light'),
        (THEME_DARK, 'Dark'),
        (THEME_SYSTEM, 'System'),
    ]
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default=ROLE_STUDENT)
    department  = models.CharField(max_length=100, blank=True)
    employee_id = models.CharField(max_length=50, blank=True)
    student_id  = models.CharField(max_length=50, blank=True)
    theme_preference = models.CharField(
        max_length=10, 
        choices=THEME_CHOICES, 
        default=THEME_SYSTEM,
        help_text='User theme preference: light, dark, or system default'
    )
    # Instructor who originally created this student account (audit trail)
    created_by  = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='created_students',
        limit_choices_to={'role': 'instructor'},
    )
    # Many-to-many roster: which instructors have uploaded / claimed this student.
    # Replaces the single-instructor visibility restriction of created_by.
    roster_instructors = models.ManyToManyField(
        'self',
        symmetrical=False,
        blank=True,
        related_name='student_roster',
    )

    @property
    def is_instructor(self):
        return self.role == self.ROLE_INSTRUCTOR

    @property
    def is_student(self):
        return self.role == self.ROLE_STUDENT

    def __str__(self):
        return f"{self.get_full_name() or self.username} ({self.role})"


class Course(models.Model):
    SEMESTER_CHOICES = [
        ('1st', '1st Semester'),
        ('2nd', '2nd Semester'),
        ('summer', 'Summer'),
    ]
    PROGRAM_CHOICES = [
        ('IT',  'Information Technology'),
        ('CS',  'Computer Science'),
        ('CE',  'Computer Engineering'),
    ]
    STATUS_CHOICES = [
        ('pending',    'Processing…'),
        ('draft',      'Draft — Review Required'),
        ('confirmed',  'Confirmed'),
        ('ready',      'Ready'),
        ('failed',     'Failed'),
    ]

    instructor    = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='courses',
        limit_choices_to={'role': 'instructor'}
    )
    # ── Fields extracted from syllabus ────────────────────────────────────────
    code          = models.CharField(max_length=30, blank=True)
    title         = models.CharField(max_length=200, blank=True)
    prerequisite  = models.CharField(max_length=200, blank=True)
    credit_units  = models.CharField(max_length=50, blank=True)   # e.g. "3 units"
    hours         = models.CharField(max_length=100, blank=True)  # e.g. "2 hrs lec, 3 hrs lab"
    description   = models.TextField(blank=True)
    semester      = models.CharField(max_length=20, choices=SEMESTER_CHOICES, default='1st')
    school_year   = models.CharField(max_length=20, default='2024-2025')
    block         = models.CharField(max_length=20, blank=True)    # e.g. "3B", "4A"
    time_frame    = models.CharField(max_length=100, blank=True)   # e.g. "MWF 7:30-9:00 AM"
    program       = models.CharField(max_length=10, choices=PROGRAM_CHOICES, blank=True)  # IT / CS / CE

    # ── Grading weights (must sum to 100) ─────────────────────────────────────
    cs_weight     = models.PositiveSmallIntegerField(default=20)   # Class Standing %
    req_weight    = models.PositiveSmallIntegerField(default=20)   # Performance Task % (was 40)
    ao_weight     = models.PositiveSmallIntegerField(default=20)   # Activity Output %
    exam_weight   = models.PositiveSmallIntegerField(default=40)   # Examinations %

    # ── Section names (custom labels for grading sheets) ────────────────────────
    cs_section_name   = models.CharField(max_length=100, blank=True, default='')
    pt_section_name   = models.CharField(max_length=100, blank=True, default='')
    ao_section_name   = models.CharField(max_length=100, blank=True, default='')
    exam_section_name = models.CharField(max_length=100, blank=True, default='')

    # ── Max scores per component (Midterm) ────────────────────────────────────
    quiz_max_scores    = models.JSONField(default=list, blank=True)  # CS highest possible scores per column
    pt_max_scores      = models.JSONField(default=list, blank=True)  # PT highest possible scores per column
    activity_max_scores = models.JSONField(default=list, blank=True)  # AO highest possible scores per column
    requirement_max    = models.PositiveSmallIntegerField(default=10)  # Major Exam highest possible score
    midterm_max        = models.PositiveSmallIntegerField(default=100)
    final_max          = models.PositiveSmallIntegerField(default=100)

    # ── Max scores per component (Final term) ─────────────────────────────────
    final_cs_max_scores       = models.JSONField(default=list, blank=True)  # Final CS highest possible scores
    final_pt_max_scores       = models.JSONField(default=list, blank=True)  # Final PT highest possible scores
    final_activity_max_scores = models.JSONField(default=list, blank=True)  # Final AO highest possible scores
    final_exam_max            = models.PositiveSmallIntegerField(default=100)  # Final Major Exam max

    # Additional fields for comprehensive syllabus extraction
    performance_target = models.TextField(blank=True)
    gad_themes = models.TextField(blank=True)
    grading_system = models.TextField(blank=True)

    # ── Structured data (JSON) ────────────────────────────────────────────────
    clos          = models.JSONField(default=list, blank=True)
    # [{code, description, ilo_codes, plo_codes}]

    weekly_plan   = models.JSONField(default=list, blank=True)
    # [{week, label, cilos, topics, methodology, resources, assessment, clo_codes}]

    # ── Raw syllabus file ──────────────────────────────────────────────────────
    syllabus_file = models.FileField(upload_to='syllabi/', blank=True)
    raw_text      = models.TextField(blank=True)   # extracted plain text

    # ── Processing status ──────────────────────────────────────────────────────
    status        = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                     default='pending')
    error_msg     = models.TextField(blank=True)

    is_active     = models.BooleanField(default=True)
    created_at    = models.DateTimeField(auto_now_add=True)
    join_code     = models.CharField(max_length=6, unique=True, blank=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['instructor', 'code', 'semester', 'school_year'],
                condition=models.Q(code__gt=''),
                name='unique_course_per_instructor_semester',
            )
        ]

    def save(self, *args, **kwargs):
        if not self.join_code:
            self.join_code = _generate_join_code()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.code} — {self.title}" if self.code else f"Course #{self.pk}"

    def get_student_count(self):
        return self.enrollments.count()
    
    def get_status_badge_class(self):
        """Return Bootstrap badge class based on status."""
        status_classes = {
            'pending': 'bg-info',
            'draft': 'bg-warning',
            'confirmed': 'bg-success',
            'ready': 'bg-primary',
            'failed': 'bg-danger',
        }
        return status_classes.get(self.status, 'bg-secondary')
    
    def can_be_confirmed(self):
        """Check if course can be confirmed (has minimum required data)."""
        return bool(self.code and self.title and self.description)
    
    def get_completion_percentage(self):
        """Calculate how complete the course data is."""
        total_fields = 10  # Reduced from 12 (removed performance_target and gad_themes)
        filled_fields = sum([
            bool(self.code),
            bool(self.title),
            bool(self.prerequisite),
            bool(self.credit_units),
            bool(self.hours),
            bool(self.description),
            bool(self.grading_system),
            bool(self.clos),
            bool(self.weekly_plan),
            bool(self.syllabus_file),
        ])
        return int((filled_fields / total_fields) * 100)


class SystemLog(models.Model):
    ACTION_CHOICES = [
        ('login',              'Login'),
        ('logout',             'Logout'),
        ('login_failed',       'Failed Login'),
        ('create_student',     'Student Created'),
        ('create_instructor',  'Instructor Created'),
        ('create_admin',       'Admin Created'),
        ('edit_user',          'User Edited'),
        ('delete_user',        'User Deleted'),
        ('create_course',      'Course Created'),
        ('delete_course',      'Course Deleted'),
        ('grade_update',       'Grades Updated'),
        ('enrollment_update',  'Enrollment Updated'),
        ('attendance',         'Attendance Recorded'),
        ('password_change',    'Password Changed'),
        ('syllabus_upload',    'Syllabus Uploaded'),
    ]
    actor      = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='activity_logs'
    )
    action     = models.CharField(max_length=30, choices=ACTION_CHOICES)
    target     = models.CharField(max_length=200, blank=True)
    detail     = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        ts = self.timestamp.strftime('%Y-%m-%d %H:%M') if self.timestamp else '?'
        actor = str(self.actor) if self.actor else 'System'
        return f"[{ts}] {actor} — {self.get_action_display()}"


class Enrollment(models.Model):
    student   = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='enrollments',
        limit_choices_to={'role': 'student'}
    )
    course    = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='enrollments')
    enrolled_at     = models.DateTimeField(auto_now_add=True)
    joined_via_code = models.BooleanField(default=False)

    class Meta:
        unique_together = ('student', 'course')
        ordering = ['student__last_name', 'student__first_name']

    def __str__(self):
        return f"{self.student} → {self.course}"