from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, HTML, Field
from .models import LessonPlan


class LessonGenerateForm(forms.ModelForm):
    class Meta:
        model = LessonPlan
        fields = ['topic', 'week_number', 'objectives']
        widgets = {
            'objectives': forms.Textarea(attrs={
                'rows': 4,
                'placeholder': (
                    'e.g. At the end of this lesson, students should be able to:\n'
                    '1. Define key concepts\n'
                    '2. Explain the main principles\n'
                    '3. Apply the concepts to real-world problems'
                )
            }),
            'topic': forms.TextInput(attrs={
                'placeholder': 'e.g. Introduction to Object-Oriented Programming'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(
                Column('topic', css_class='col-md-9'),
                Column('week_number', css_class='col-md-3'),
            ),
            'objectives',
            HTML("""
                <div class="alert alert-info py-2 mt-2" style="font-size:.825rem;">
                    <i class="bi bi-robot"></i>
                    AI will use your <strong>course syllabus</strong> to generate a
                    relevant lesson plan and downloadable PowerPoint.
                    Generation takes about 15–30 seconds.
                </div>
            """),
            Submit('submit', '✦ Generate Lesson Plan',
                   css_class='btn btn-primary mt-2')
        )