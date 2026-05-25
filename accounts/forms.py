from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Submit, Row, Column, Field, HTML
from .models import User, Course, Enrollment


class RegisterForm(UserCreationForm):
    first_name = forms.CharField(max_length=50, required=True)
    last_name  = forms.CharField(max_length=50, required=True)
    email      = forms.EmailField(required=True)
    role       = forms.ChoiceField(choices=User.ROLE_CHOICES)
    department = forms.CharField(max_length=100, required=False)
    employee_id = forms.CharField(max_length=50, required=False,
                                   label='Employee ID (Instructors only)')
    student_id  = forms.CharField(max_length=50, required=False,
                                   label='Student ID (Students only)')

    class Meta:
        model  = User
        fields = ['username', 'first_name', 'last_name', 'email',
                  'role', 'department', 'employee_id', 'student_id',
                  'password1', 'password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(Column('first_name'), Column('last_name')),
            'username', 'email',
            Row(Column('role'), Column('department')),
            Row(Column('employee_id'), Column('student_id')),
            'password1', 'password2',
            Submit('submit', 'Create Account', css_class='btn btn-primary w-100 mt-2')
        )
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Field('username', placeholder='Username'),
            Field('password', placeholder='Password'),
            Submit('submit', 'Sign In', css_class='btn btn-primary w-100 mt-2')
        )
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class SyllabusUploadForm(forms.Form):
    """
    Single-field form — instructor just uploads the .docx syllabus.
    """
    syllabus_file = forms.FileField(
        label='Upload Syllabus (.docx or .pdf)',
        help_text='Upload your course syllabus in Word or PDF format. '
                  'The system will automatically extract all course information.',
        widget=forms.ClearableFileInput(attrs={'accept': '.docx,.pdf', 'class': 'form-control'})
    )
    program = forms.ChoiceField(
        label='Program / Course',
        required=False,
        choices=[('', 'Select Program')] + list(Course.PROGRAM_CHOICES),
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    block = forms.CharField(
        label='Block and Year',
        required=False,
        max_length=20,
        widget=forms.TextInput(
            attrs={'class': 'form-control', 'placeholder': 'e.g., 3A, 2B'}
        ),
        help_text='Optional. Example: 3A or 4B.'
    )
    school_year = forms.CharField(
        label='School Year',
        required=False,
        max_length=20,
        initial='2024-2025',
        widget=forms.TextInput(
            attrs={'class': 'form-control', 'placeholder': '2024-2025'}
        )
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            'syllabus_file',
            HTML("""
                <div class="alert alert-info py-2 mt-2" style="font-size:.825rem;">
                    <i class="bi bi-robot"></i>
                    The data will automatically extract the <strong>course code, title, prerequisites,
                    credit units, hours, description, CLOs, and full weekly plan</strong>
                    directly from your syllabus file.
                </div>
            """),
            Submit('submit', 'Upload Syllabus',
                   css_class='btn btn-primary mt-2 w-100')
        )

    def clean_syllabus_file(self):
        f = self.cleaned_data['syllabus_file']
        if not (f.name.endswith('.docx') or f.name.endswith('.pdf')):
            raise forms.ValidationError('Only .docx and .pdf files are supported.')
        if f.size > 10 * 1024 * 1024:  # 10 MB
            raise forms.ValidationError('File size must be under 10 MB.')
        return f


class CreateStudentForm(forms.ModelForm):
    """
    Instructor-facing form to create a single student account.
    Password defaults to student_id if provided, otherwise username.
    """
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Leave blank to use Student ID or username'}),
        required=False,
        help_text='Leave blank to auto-set password to Student ID (or username if no ID).',
    )

    class Meta:
        model  = User
        fields = ['first_name', 'last_name', 'username', 'email',
                  'student_id', 'department']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.fields['username'].required = True
        self.fields['email'].required = False

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError(f'Username "{username}" is already taken.')
        return username

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.ROLE_STUDENT
        raw_pw = self.cleaned_data.get('password') or self.cleaned_data.get('student_id') or user.username
        user.set_password(raw_pw)
        if commit:
            user.save()
        return user


class CreateUserForm(forms.ModelForm):
    """
    Admin portal form — creates any role (student / instructor / admin).
    """
    ROLE_EXTENDED = [
        ('student',    'Student'),
        ('instructor', 'Instructor'),
        ('admin',      'Administrator (superuser)'),
    ]
    role_choice = forms.ChoiceField(
        choices=ROLE_EXTENDED, label='Role',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Leave blank → uses Student ID or username'}),
        required=False, label='Password',
        help_text='If blank, defaults to Student ID → username.'
    )

    class Meta:
        model  = User
        fields = ['first_name', 'last_name', 'username', 'email',
                  'department', 'employee_id', 'student_id']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            if name != 'role_choice':
                field.widget.attrs['class'] = 'form-control'
        self.fields['first_name'].required = True
        self.fields['last_name'].required = True
        self.fields['username'].required  = True
        self.fields['email'].required     = False

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError(f'Username "{username}" is already taken.')
        return username

    def save(self, commit=True):
        user = super().save(commit=False)
        role_choice = self.cleaned_data['role_choice']
        raw_pw = (
            self.cleaned_data.get('password') or
            self.cleaned_data.get('student_id') or
            user.username
        )
        user.set_password(raw_pw)
        if role_choice == 'admin':
            user.is_staff      = True
            user.is_superuser  = True
            user.role          = User.ROLE_INSTRUCTOR  # fallback for non-admin checks
        else:
            user.role = role_choice
        if commit:
            user.save()
        return user


class CourseEditForm(forms.ModelForm):
    """
    Used to manually correct AI-extracted data if needed.
    """
    class Meta:
        model  = Course
        fields = ['code', 'title', 'prerequisite', 'credit_units',
                  'hours', 'semester', 'school_year', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.layout = Layout(
            Row(Column('code', css_class='col-md-4'),
                Column('title', css_class='col-md-8')),
            Row(Column('prerequisite', css_class='col-md-6'),
                Column('credit_units', css_class='col-md-3'),
                Column('hours', css_class='col-md-3')),
            Row(Column('semester'), Column('school_year')),
            'description',
            Submit('submit', 'Save Changes', css_class='btn btn-primary mt-2')
        )