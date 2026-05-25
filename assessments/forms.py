import json
from django import forms
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, HTML, Field
from .models import Question


class QuestionEditForm(forms.ModelForm):
    """Form for manually editing a generated question."""

    choices_raw = forms.CharField(
        label='Choices (JSON)',
        required=False,
        widget=forms.Textarea(attrs={'rows': 4}),
        help_text='For multiple-choice only. Format: {"A": "...", "B": "...", "C": "...", "D": "..."}'
    )

    class Meta:
        model = Question
        fields = [
            'topic', 'week_ref', 'question_type', 'bloom_level', 'difficulty',
            'content', 'answer_key', 'explanation', 'rubric',
            'expected_answer', 'follow_up',
        ]
        widgets = {
            'content':         forms.Textarea(attrs={'rows': 3}),
            'explanation':     forms.Textarea(attrs={'rows': 2}),
            'rubric':          forms.Textarea(attrs={'rows': 2}),
            'expected_answer': forms.Textarea(attrs={'rows': 2}),
            'follow_up':       forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        if instance and instance.choices:
            self.fields['choices_raw'].initial = json.dumps(instance.choices, indent=2)

        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(
                Column('topic',         css_class='col-md-6'),
                Column('week_ref',      css_class='col-md-2'),
                Column('question_type', css_class='col-md-4'),
            ),
            Row(
                Column('bloom_level', css_class='col-md-4'),
                Column('difficulty',  css_class='col-md-4'),
            ),
            'content',
            'choices_raw',
            'answer_key',
            'explanation',
            'rubric',
            'expected_answer',
            'follow_up',
            Submit('submit', 'Save Changes', css_class='btn btn-primary mt-2'),
        )

    def clean_choices_raw(self):
        raw = self.cleaned_data.get('choices_raw', '').strip()
        if not raw:
            return None
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise forms.ValidationError('Choices must be a JSON object.')
            return data
        except json.JSONDecodeError as e:
            raise forms.ValidationError(f'Invalid JSON: {e}')

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.choices = self.cleaned_data.get('choices_raw')
        if commit:
            instance.save()
        return instance


class QuestionGenerateForm(forms.Form):
    assessment_type = forms.ChoiceField(
        label='Assessment Type',
        choices=[('quiz', 'Normal Quiz'), ('exam', 'Major Exam')],
        initial='quiz',
        required=True,
        help_text='Exams tend to have slightly more comprehensive or integrative questions.'
    )
    weeks = forms.MultipleChoiceField(
        label='Select Weeks',
        required=False,
        help_text='Choose one or more weeks to generate questions for each.'
    )
    custom_topic = forms.CharField(
        label='Custom topic (optional)',
        required=False,
        help_text='Override with a specific topic if needed (applies to all selected weeks).'
    )

    def __init__(self, *args, weekly_plan=None, **kwargs):
        super().__init__(*args, **kwargs)
        if weekly_plan:
            choices = []
            for item in weekly_plan:
                # `item` is a dict with keys like 'week', 'topics'
                wn = item.get('week')
                if wn is None:
                    continue
                
                # topics could be a list or a string
                raw_topics = item.get('topics', '')
                if isinstance(raw_topics, list):
                    topic_str = ', '.join(str(t) for t in raw_topics)
                else:
                    topic_str = str(raw_topics)
                    
                label = f"Week {wn} — {topic_str[:45]}"
                if len(topic_str) > 45:
                    label += "..."
                choices.append((f"Week {wn}|{topic_str}", label))

            self.fields['weeks'] = forms.MultipleChoiceField(
                choices=choices, label='Select Weeks', required=False
            )

        self.helper = FormHelper()
        self.helper.layout = Layout('weeks', 'custom_topic')