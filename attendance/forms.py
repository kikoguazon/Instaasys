from django import forms
from .models import AttendanceSession


class AttendanceSessionForm(forms.ModelForm):
    class Meta:
        model  = AttendanceSession
        fields = ['date', 'time_start', 'time_end', 'notes']
        widgets = {
            'date': forms.DateInput(
                attrs={'type': 'date', 'class': 'form-control'}
            ),
            'time_start': forms.TimeInput(
                attrs={'type': 'time', 'class': 'form-control'}
            ),
            'time_end': forms.TimeInput(
                attrs={'type': 'time', 'class': 'form-control'}
            ),
            'notes': forms.TextInput(
                attrs={'class': 'form-control', 'placeholder': 'Optional notes'}
            ),
        }
