from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, HTML


class TOSForm(forms.Form):
    EXAM_CHOICES = [
        ('Midterm Examination', 'Midterm Examination'),
        ('Final Examination', 'Final Examination'),
        ('Quarterly Exam', 'Quarterly Exam'),
        ('Unit Test', 'Unit Test'),
    ]
    exam_type   = forms.ChoiceField(choices=EXAM_CHOICES)
    total_items = forms.IntegerField(min_value=10, max_value=200, initial=50)
    topics_json = forms.CharField(
        widget=forms.HiddenInput(),
        required=False
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(Column('exam_type'), Column('total_items')),
            'topics_json',
            HTML("""
                <div class="alert alert-info py-2" style="font-size:.825rem;">
                    <i class="bi bi-table"></i>
                    Add topics and hours below, then generate your TOS.
                </div>
            """),
            Submit('submit', '✦ Generate TOS',
                   css_class='btn btn-success mt-2')
        )
