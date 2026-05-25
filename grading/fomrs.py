from django import forms


class QuizScoreForm(forms.Form):
    """Dynamically built form for entering all student grades in one table."""
    pass


class GradeWeightForm(forms.Form):
    """Shown at the top of the e-class record to configure weights."""
    CLASS_STANDING_WEIGHT = forms.IntegerField(
        initial=20, min_value=0, max_value=100,
        label='Class Standing %'
    )
    REQUIREMENTS_WEIGHT = forms.IntegerField(
        initial=40, min_value=0, max_value=100,
        label='Requirements %'
    )
    EXAMINATIONS_WEIGHT = forms.IntegerField(
        initial=40, min_value=0, max_value=100,
        label='Examinations %'
    )