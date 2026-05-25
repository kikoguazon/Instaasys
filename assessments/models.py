from django.db import models


class QuestionSet(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_READY   = 'ready'
    STATUS_FAILED  = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Generating…'),
        (STATUS_READY,   'Ready'),
        (STATUS_FAILED,  'Failed'),
    ]

    course      = models.ForeignKey(
        'accounts.Course', on_delete=models.CASCADE,
        related_name='question_sets'
    )
    title       = models.CharField(max_length=300)
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    error_msg   = models.TextField(blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Question Set'
        verbose_name_plural = 'Question Sets'

    def __str__(self):
        return f"{self.course.code} - {self.title}"


class Question(models.Model):
    TYPE_CHOICES = [
        ('multiple_choice', 'Multiple Choice'),
        ('true_false',      'True or False'),
        ('identification',  'Identification'),
        ('essay',           'Essay / Short Answer'),
        ('oral',            'Oral / Discussion'),
    ]
    BLOOM_CHOICES = [
        ('remember',   'Remember'),
        ('understand', 'Understand'),
        ('apply',      'Apply'),
        ('analyze',    'Analyze'),
        ('evaluate',   'Evaluate'),
        ('create',     'Create'),
    ]
    DIFFICULTY_CHOICES = [
        ('easy',   'Easy'),
        ('average','Average'),
        ('hard',   'Hard'),
    ]

    course        = models.ForeignKey(
        'accounts.Course', on_delete=models.CASCADE,
        related_name='questions'
    )
    question_set  = models.ForeignKey(
        QuestionSet, on_delete=models.CASCADE,
        related_name='questions', null=True, blank=True
    )
    topic         = models.TextField()
    week_ref      = models.CharField(max_length=20, blank=True)  # e.g. "Week 1-2"
    question_type = models.CharField(max_length=20, choices=TYPE_CHOICES,
                                     default='multiple_choice')
    bloom_level   = models.CharField(max_length=20, choices=BLOOM_CHOICES,
                                     default='remember')
    difficulty    = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES,
                                     default='average')

    content       = models.TextField()
    # Multiple choice: {"A": "...", "B": "...", "C": "...", "D": "..."}
    choices       = models.JSONField(null=True, blank=True)
    answer_key    = models.TextField(blank=True)
    explanation   = models.TextField(blank=True)

    # Essay/Oral extras
    rubric        = models.TextField(blank=True)
    expected_answer = models.TextField(blank=True)
    follow_up     = models.TextField(blank=True)

    created_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['topic', 'bloom_level', '-created_at']

    def __str__(self):
        return f"[{self.get_question_type_display()}] {self.content[:60]}"