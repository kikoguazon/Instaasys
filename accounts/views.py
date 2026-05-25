import os
import csv
import io
import tempfile
import logging
import json
import secrets
import shutil
from pathlib import Path
from datetime import timedelta
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from django.db import models as django_models
from django.conf import settings
from .models import User, Course, Enrollment, SystemLog
from .forms import RegisterForm, LoginForm, SyllabusUploadForm, CourseEditForm, CreateStudentForm, CreateUserForm
from grading.models import GradeRecord

logger = logging.getLogger(__name__)


def _cleanup_temp_syllabus_file(request):
    """Remove temp syllabus file if present in session."""
    temp_path = request.session.pop('syllabus_temp_path', None)
    if temp_path and os.path.exists(temp_path):
        try:
            os.unlink(temp_path)
        except OSError:
            pass


# ─── Logging helper ───────────────────────────────────────────────────────────

def _log(request_or_actor, action, target='', detail=''):
    """Write a SystemLog entry. Pass request to capture IP, or a User directly."""
    ip = None
    actor = None
    if hasattr(request_or_actor, 'user'):
        req = request_or_actor
        actor = req.user if req.user.is_authenticated else None
        xff = req.META.get('HTTP_X_FORWARDED_FOR', '')
        ip  = xff.split(',')[0].strip() if xff else req.META.get('REMOTE_ADDR')
    else:
        actor = request_or_actor  # passed a User object directly
    try:
        SystemLog.objects.create(
            actor=actor, action=action, target=target,
            detail=detail, ip_address=ip,
        )
    except Exception:
        pass  # never crash the main flow because of logging


# ─── Landing & About ──────────────────────────────────────────────────────────

def landing_view(request):
    """Modern landing page with animations and features."""
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')
    return render(request, 'landing.html')


def about_view(request):
    """About page explaining the system."""
    return render(request, 'about.html')


# ─── Auth ─────────────────────────────────────────────────────────────────────

def register_view(request):
    """
    Public registration is disabled.
    Accounts are created by admins (instructors) via Django admin or the
    instructor portal. This view shows an informational page.
    """
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')
    return render(request, 'accounts/register_disabled.html')


def login_view(request):
    if request.user.is_authenticated:
        return redirect('accounts:dashboard')
    if request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            _log(request, 'login', target=user.username,
                 detail=f'Role: {"admin" if user.is_superuser else user.role}')
            messages.success(request, f'Welcome back, {user.first_name}!')
            return redirect('accounts:dashboard')
        else:
            attempted = request.POST.get('username', '')
            _log(request, 'login_failed', target=attempted,
                 detail='Invalid credentials')
            messages.error(request, 'Invalid username or password.')
    else:
        form = LoginForm()
    return render(request, 'accounts/login.html', {'form': form})


def logout_view(request):
    if request.user.is_authenticated:
        _log(request, 'logout', target=request.user.username)
    logout(request)
    return redirect('accounts:login')


@login_required
def dashboard(request):
    if request.user.is_superuser:
        return redirect('accounts:portal_dashboard')
    if request.user.is_instructor:
        return redirect('accounts:instructor_dashboard')
    return redirect('accounts:student_dashboard')


# ─── Instructor ───────────────────────────────────────────────────────────────

@login_required
def instructor_dashboard(request):
    if not request.user.is_instructor:
        return redirect('accounts:student_dashboard')
    courses = Course.objects.filter(instructor=request.user)
    context = {
        'courses': courses,
        'total_courses': courses.count(),
        'total_students': Enrollment.objects.filter(
            course__instructor=request.user).count(),
    }
    return render(request, 'accounts/instructor_dashboard.html', context)


@login_required
def course_list(request):
    if not request.user.is_instructor:
        return redirect('accounts:student_dashboard')

    courses_qs = Course.objects.filter(instructor=request.user).distinct()

    q = request.GET.get('q', '').strip()
    if q:
        courses_qs = courses_qs.filter(
            django_models.Q(title__icontains=q) | django_models.Q(code__icontains=q)
        )

    total_count = courses_qs.count()
    paginator = Paginator(courses_qs, 9)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    # JSON branch for infinite scroll / debounced search
    if request.GET.get('format') == 'json':
        from django.template.loader import render_to_string
        html = render_to_string(
            'accounts/partials/course_cards.html',
            {'courses': page_obj, 'request': request},
        )
        return JsonResponse({
            'html': html,
            'has_next': page_obj.has_next(),
            'next_page': page_obj.next_page_number() if page_obj.has_next() else None,
            'total': total_count,
        })

    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'accounts/course_list.html', {
        'courses': page_obj,
        'page_obj': page_obj,
        'page_query': params.urlencode(),
        'total_count': total_count,
        'search': q,
    })


@login_required
def syllabus_upload(request):
    """
    Replaces manual course creation.
    Instructor uploads a .docx → AI extracts all fields → Shows confirmation → Course is created.
    """
    if not request.user.is_instructor:
        return redirect('accounts:student_dashboard')

    if request.method == 'POST':
        # Handle confirmation form submission
        if 'action' in request.POST and request.POST.get('action') == 'confirm':
            confirm_action = request.POST.get('confirm')
            
            # Get the extracted data from session
            extracted_data = request.session.get('extracted_syllabus_data', {})
            if not extracted_data:
                logger.warning(f"Session expired or missing data. Session keys: {list(request.session.keys())}")
                messages.error(request, 'Session expired. Please upload the syllabus again.')
                return redirect('accounts:syllabus_upload')
            
            if confirm_action == 'create':
                submitted_token = request.POST.get('create_token', '')
                expected_token = request.session.get('syllabus_create_token', '')
                if not expected_token or submitted_token != expected_token:
                    messages.warning(
                        request,
                        'This syllabus has already been submitted or your session expired. '
                        'Please upload again if you need to create another subject.'
                    )
                    return redirect('accounts:syllabus_upload')

                # Create the course with extracted data (prevent duplicates)
                try:
                    _code        = request.POST.get('code', '').strip()
                    _semester    = request.POST.get('semester', '1st')
                    _school_year = request.POST.get('school_year', '2024-2025')
                    _fields = dict(
                        program      = request.POST.get('program', ''),
                        title        = request.POST.get('title', 'Untitled Course'),
                        prerequisite = request.POST.get('prerequisite', ''),
                        credit_units = request.POST.get('credit_units', ''),
                        hours        = request.POST.get('hours', ''),
                        block        = request.POST.get('block', ''),
                        time_frame   = request.POST.get('time_frame', ''),
                        description  = request.POST.get('description', ''),
                        performance_target = request.POST.get('performance_target', ''),
                        gad_themes   = request.POST.get('gad_themes', ''),
                        clos         = extracted_data.get('clos', []),
                        weekly_plan  = extracted_data.get('weekly_plan', []),
                        raw_text     = extracted_data.get('raw_text', ''),
                        status       = 'draft',
                    )
                    if _code:
                        course, _created = Course.objects.get_or_create(
                            instructor=request.user,
                            code=_code,
                            semester=_semester,
                            school_year=_school_year,
                            defaults=_fields,
                        )
                        if not _created:
                            for _k, _v in _fields.items():
                                setattr(course, _k, _v)
                            course.save()
                    else:
                        course = Course.objects.create(
                            instructor=request.user,
                            code=_code,
                            semester=_semester,
                            school_year=_school_year,
                            **_fields,
                        )
                except Exception as e:
                    logger.error(f"Failed to create course: {e}")
                    messages.error(request, f'Failed to create course: {e}')
                    return redirect('accounts:syllabus_upload')

                request.session.pop('syllabus_create_token', None)
                
                # Save the original file from session
                temp_path = request.session.get('syllabus_temp_path')
                temp_ext = request.session.get('syllabus_temp_ext', '.docx')
                if temp_path and os.path.exists(temp_path):
                    with open(temp_path, 'rb') as f:
                        course.syllabus_file.save(
                            f"syllabus_{course.pk}{temp_ext}",
                            ContentFile(f.read()),
                            save=True
                        )
                    _cleanup_temp_syllabus_file(request)
                    request.session.pop('syllabus_temp_ext', None)
                
                # Clean up session data
                if 'extracted_syllabus_data' in request.session:
                    del request.session['extracted_syllabus_data']
                
                messages.success(request,
                    f'Course created successfully: {course.code} — {course.title}')
                return redirect('accounts:course_detail', pk=course.pk)
                
            elif confirm_action == 'false':
                # Cancel and go back to upload
                _cleanup_temp_syllabus_file(request)
                request.session.pop('syllabus_temp_ext', None)
                if 'extracted_syllabus_data' in request.session:
                    del request.session['extracted_syllabus_data']
                request.session.pop('syllabus_create_token', None)
                messages.info(request, 'Upload cancelled. You can upload a different file.')
                return redirect('accounts:syllabus_upload')
                
            elif confirm_action == 'edit':
                # Store data in session for editing
                try:
                    request.session['pending_course_data'] = {
                        'program': request.POST.get('program', ''),
                        'code': request.POST.get('code', ''),
                        'title': request.POST.get('title', ''),
                        'prerequisite': request.POST.get('prerequisite', ''),
                        'credit_units': request.POST.get('credit_units', ''),
                        'hours': request.POST.get('hours', ''),
                        'semester': request.POST.get('semester', '1st'),
                        'school_year': request.POST.get('school_year', ''),
                        'block': request.POST.get('block', ''),
                        'time_frame': request.POST.get('time_frame', ''),
                        'description': request.POST.get('description', ''),
                        'performance_target': request.POST.get('performance_target', ''),
                        'gad_themes': request.POST.get('gad_themes', ''),
                        'clos': extracted_data.get('clos', []),
                        'weekly_plan': extracted_data.get('weekly_plan', []),
                        'raw_text': extracted_data.get('raw_text', ''),
                    }
                    request.session.pop('syllabus_create_token', None)
                    messages.info(request, 'You can now edit the course information before creating it.')
                    return redirect('accounts:course_create_from_syllabus')
                except Exception as e:
                    logger.error(f"Failed to prepare edit data: {e}")
                    messages.error(request, f'Failed to prepare edit data: {e}')
                    return redirect('accounts:syllabus_upload')

            else:
                logger.warning(f"Invalid syllabus confirmation action: {confirm_action!r}")
                messages.warning(request, 'Invalid confirmation action. Please try again.')
                return redirect('accounts:syllabus_upload')

        # Handle initial upload
        form = SyllabusUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded = request.FILES['syllabus_file']

            # Save to a temp file so parser can read it
            suffix = '.pdf' if uploaded.name.endswith('.pdf') else '.docx'
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                for chunk in uploaded.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name

            try:
                from instaasys.syllabus_parser import process_syllabus_file
                data = process_syllabus_file(tmp_path)
            except Exception as exc:
                logger.error(f"Syllabus parsing failed: {exc}")
                messages.error(request,
                    f'Could not parse syllabus: {exc}. '
                    f'Make sure the file is a valid syllabus.')
                os.unlink(tmp_path)
                return render(request, 'accounts/syllabus_upload.html', {'form': form})

            # Move uploaded file into a local temp storage and keep only path in session.
            upload_tmp_dir = Path(settings.MEDIA_ROOT) / 'tmp_syllabus'
            upload_tmp_dir.mkdir(parents=True, exist_ok=True)
            stored_name = f"upload_{secrets.token_urlsafe(12)}{suffix}"
            stored_path = upload_tmp_dir / stored_name
            shutil.move(tmp_path, str(stored_path))

            form_program = form.cleaned_data.get('program') or ''
            form_block = form.cleaned_data.get('block') or ''
            form_school_year = form.cleaned_data.get('school_year') or '2024-2025'
            if form_program:
                data['program'] = form_program
            if form_block:
                data['block'] = form_block
            if form_school_year:
                data['school_year'] = form_school_year

            # Keep only temp file location in session to avoid heavy session payload.
            _cleanup_temp_syllabus_file(request)
            request.session['syllabus_temp_path'] = str(stored_path)
            request.session['syllabus_temp_ext'] = suffix

            # Store the extracted data in session for form processing
            request.session['extracted_syllabus_data'] = data
            request.session['syllabus_create_token'] = secrets.token_urlsafe(24)
            request.session.modified = True  # Ensure session is saved
            logger.info(f"Stored syllabus data in session. Session key: {request.session.session_key}")
            logger.info(f"Session keys after storage: {list(request.session.keys())}")

            # Calculate extraction quality
            total_fields = 12  # Total fields we try to extract
            filled_fields = 0
            if data.get('code'): filled_fields += 1
            if data.get('title'): filled_fields += 1
            if data.get('prerequisite'): filled_fields += 1
            if data.get('credit_units'): filled_fields += 1
            if data.get('hours'): filled_fields += 1
            if data.get('semester'): filled_fields += 1
            if data.get('school_year'): filled_fields += 1
            if data.get('description'): filled_fields += 1
            if data.get('performance_target'): filled_fields += 1
            if data.get('gad_themes'): filled_fields += 1
            if data.get('grading_system'): filled_fields += 1
            if data.get('clos'): filled_fields += 1
            
            extraction_percentage = int((filled_fields / total_fields) * 100)
            
            # Identify missing fields
            missing_fields = []
            if not data.get('code'): missing_fields.append('Course Code')
            if not data.get('title'): missing_fields.append('Course Title')
            if not data.get('credit_units'): missing_fields.append('Credit Units')
            if not data.get('hours'): missing_fields.append('Contact Hours')
            if not data.get('description'): missing_fields.append('Course Description')
            if not data.get('performance_target'): missing_fields.append('Performance Target')
            if not data.get('gad_themes'): missing_fields.append('GAD Themes')
            if not data.get('grading_system'): missing_fields.append('Grading System')
            if not data.get('clos'): missing_fields.append('Course Learning Outcomes')

            return render(request, 'accounts/syllabus_preview.html', {
                'extracted_data': data,
                'create_token': request.session['syllabus_create_token'],
                'filename': uploaded.name,
                'file_size': f"{uploaded.size / 1024:.1f} KB",
                'extraction_percentage': extraction_percentage,
                'missing_fields': missing_fields,
            })
    else:
        form = SyllabusUploadForm()

    return render(request, 'accounts/syllabus_upload.html', {'form': form})


@login_required
def course_detail(request, pk):
    course = get_object_or_404(Course, pk=pk, instructor=request.user)
    enrollments = (Enrollment.objects
                   .filter(course=course)
                   .select_related('student')
                   .order_by('student__last_name', 'student__first_name', 'student__username'))
    return render(request, 'accounts/course_detail.html',
                  {'course': course, 'enrollments': enrollments})


@login_required
def course_edit(request, pk):
    course = get_object_or_404(Course, pk=pk, instructor=request.user)
    if request.method == 'POST':
        form = CourseEditForm(request.POST, instance=course)
        if form.is_valid():
            form.save()
            messages.success(request, 'Course updated.')
            return redirect('accounts:course_detail', pk=pk)
    else:
        form = CourseEditForm(instance=course)
    return render(request, 'accounts/course_form.html',
                  {'form': form, 'course': course})


@login_required
def course_delete(request, pk):
    course = get_object_or_404(Course, pk=pk, instructor=request.user)
    if request.method == 'POST':
        title = course.title
        code  = course.code
        course.delete()
        _log(request, 'delete_course', target=code, detail=title)
        messages.success(request, f'Course "{title}" deleted.')
        return redirect('accounts:course_list')
    return render(request, 'accounts/course_confirm_delete.html', {'course': course})


@login_required
def enroll_students(request, pk):
    course = get_object_or_404(Course, pk=pk, instructor=request.user)
    enrolled_ids = list(course.enrollments.values_list('student_id', flat=True))

    if request.method == 'POST':
        selected_ids = request.POST.getlist('students')
        for sid in selected_ids:
            student = get_object_or_404(User, pk=sid, role='student')
            enrollment, created = Enrollment.objects.get_or_create(
                student=student, course=course
            )
            if created:
                GradeRecord.objects.create(enrollment=enrollment)
        course.enrollments.exclude(student_id__in=selected_ids).delete()
        _log(request, 'enrollment_update', target=course.code,
             detail=f'{len(selected_ids)} student(s) enrolled')
        messages.success(request, 'Enrollment updated.')
        return redirect('accounts:course_detail', pk=pk)

    # Only show students that are already enrolled in this specific course.
    # Non-enrolled students are hidden; instructors add new students via
    # "Add Student" modal, "Upload CSV", or the course join code.
    students = (User.objects
                .filter(
                    role='student',
                    is_superuser=False,
                    enrollments__course=course,
                )
                .distinct()
                .order_by('last_name', 'first_name', 'username'))

    return render(request, 'accounts/enroll_students.html', {
        'course':       course,
        'students':     students,
        'enrolled_ids': enrolled_ids,
    })


@login_required
def ajax_add_student(request, pk):
    """AJAX: create a student account (or find existing by student_id)
    and immediately enroll them in the course."""
    if not request.user.is_instructor:
        return JsonResponse({'success': False, 'error': 'Forbidden'}, status=403)

    course = get_object_or_404(Course, pk=pk, instructor=request.user)

    first_name  = request.POST.get('first_name', '').strip().title()
    last_name   = request.POST.get('last_name', '').strip().title()
    student_id  = request.POST.get('student_id', '').strip()
    department  = request.POST.get('department', '').strip()

    if not first_name or not last_name or not student_id:
        return JsonResponse({'success': False,
                             'error': 'First name, last name and student ID are required.'})

    # Try to find an existing account by student_id / username
    existing = User.objects.filter(
        role='student', student_id=student_id
    ).first() or User.objects.filter(
        role='student', username=student_id
    ).first()

    if existing:
        student = existing
        created_account = False
    else:
        # Create a new student account
        student = User.objects.create_user(
            username=student_id,
            first_name=first_name,
            last_name=last_name,
            password=student_id,
            role=User.ROLE_STUDENT,
            student_id=student_id,
            department=department,
            created_by=request.user,
        )
        created_account = True
        _log(request, 'create_student', target=student.username,
             detail=f'Manually added by {request.user.username} to {course.code}')

    # Always add to this instructor's roster so student appears in enrollment list
    student.roster_instructors.add(request.user)

    # Enroll in the course
    enrollment, enrolled_now = Enrollment.objects.get_or_create(
        student=student, course=course
    )
    if enrolled_now:
        GradeRecord.objects.get_or_create(enrollment=enrollment)

    return JsonResponse({
        'success':        True,
        'created_account': created_account,
        'enrolled_now':   enrolled_now,
        'student': {
            'pk':         student.pk,
            'name':       student.get_full_name(),
            'username':   student.username,
            'student_id': student.student_id,
            'email':      student.email,
        },
    })


@login_required
def course_confirm(request, pk):
    """Confirmation gate: instructor reviews extracted data and confirms."""
    course = get_object_or_404(Course, pk=pk, instructor=request.user)
    if request.method == 'POST':
        course.status = 'confirmed'
        course.save()
        messages.success(request,
            f'✓ Course "{course.code} — {course.title}" confirmed and ready for use.')
        return redirect('accounts:course_detail', pk=pk)
    return render(request, 'accounts/course_confirm.html', {'course': course})


@login_required
def course_reupload(request, pk):
    """Delete extracted data and re-upload a new syllabus file."""
    course = get_object_or_404(Course, pk=pk, instructor=request.user)
    if request.method == 'POST':
        course.delete()
        messages.info(request, 'Course data cleared. Please upload a new syllabus.')
        return redirect('accounts:syllabus_upload')
    return redirect('accounts:course_detail', pk=pk)


@login_required
def profile_view(request):
    """Settings: profile info, password change, appearance (theme)."""
    from django.contrib.auth import update_session_auth_hash
    from django.contrib.auth.forms import PasswordChangeForm

    user = request.user
    password_form = PasswordChangeForm(user)
    active_tab = request.GET.get('tab', 'profile')

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'update_profile':
            user.first_name = request.POST.get('first_name', user.first_name).strip()
            user.last_name = request.POST.get('last_name', user.last_name).strip()
            user.email = request.POST.get('email', user.email).strip()
            user.department = request.POST.get('department', user.department).strip()
            user.save()
            messages.success(request, 'Profile updated.')
            return HttpResponseRedirect(reverse('accounts:profile') + '?tab=profile')

        elif action == 'change_password':
            password_form = PasswordChangeForm(user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, 'Password changed successfully.')
                return HttpResponseRedirect(reverse('accounts:profile') + '?tab=security')
            # Re-render with security tab active on validation error
            return render(request, 'accounts/profile.html', {
                'password_form': password_form,
                'active_tab': 'security',
            })

    return render(request, 'accounts/profile.html', {
        'password_form': password_form,
        'active_tab': active_tab,
    })


# ─── Student ──────────────────────────────────────────────────────────────────

@login_required
def student_dashboard(request):
    if not request.user.is_student:
        return redirect('accounts:instructor_dashboard')

    from attendance.models import AttendanceRecord

    enrollments = Enrollment.objects.filter(
        student=request.user
    ).select_related('course', 'course__instructor', 'grade_record')

    grade_data    = []
    final_grades  = []
    passed_count  = 0
    failed_count  = 0
    pending_count = 0
    notifications = []

    seven_days_ago = timezone.now() - timedelta(days=7)

    for e in enrollments:
        rec = getattr(e, 'grade_record', None)
        fg  = rec.final_grade if rec else None

        if fg is not None:
            final_grades.append(fg)
            if rec.passed:
                passed_count += 1
            else:
                failed_count += 1
        else:
            pending_count += 1

        # Notification: grade posted/updated within the last 7 days
        if rec and rec.updated_at and rec.updated_at >= seven_days_ago:
            notifications.append({
                'course':     e.course,
                'updated_at': rec.updated_at,
            })

        # Quick attendance stats for this course
        att_qs      = AttendanceRecord.objects.filter(enrollment=e)
        att_total   = att_qs.count()
        att_present = att_qs.filter(status='present').count()
        att_late    = att_qs.filter(status='late').count()
        att_pct     = round((att_present + att_late) / att_total * 100, 1) if att_total else None

        grade_data.append({
            'enrollment': e,
            'course':     e.course,
            'record':     rec,
            'att_pct':    att_pct,
            'att_total':  att_total,
        })

    gwa = round(sum(final_grades) / len(final_grades), 2) if final_grades else None

    context = {
        'grade_data':     grade_data,
        'gwa':            gwa,
        'passed_count':   passed_count,
        'failed_count':   failed_count,
        'pending_count':  pending_count,
        'total_courses':  enrollments.count(),
        'graded_courses': len(final_grades),
        'notifications':  notifications,
    }
    return render(request, 'accounts/student_dashboard.html', context)


@login_required
def upload_students_csv(request):
    """
    Instructor uploads a CSV to bulk-create student accounts.

    Supports NEMSU format:
        student_id, last_name, first_name, Middle_Initial, Course_Section
    Also accepts legacy format:
        first_name, last_name, username, email[, student_id, department]

    Username is derived from student_id (e.g. 2023-0145).
    Password defaults to student_id; falls back to username.

    If a course_pk is provided (e.g. from the enrollment page upload tab),
    all processed students are automatically enrolled in that course.
    """
    if not request.user.is_instructor:
        return redirect('accounts:student_dashboard')

    results   = None
    next_url  = request.POST.get('next') or request.GET.get('next') or ''

    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']

        # Resolve optional target course for auto-enrollment
        course_pk  = request.POST.get('course_pk') or request.GET.get('course_pk')
        target_course = None
        if course_pk:
            try:
                target_course = Course.objects.get(pk=course_pk, instructor=request.user)
            except Course.DoesNotExist:
                pass

        if not csv_file.name.endswith('.csv'):
            messages.error(request, 'Please upload a valid .csv file.')
            return redirect(next_url or 'accounts:upload_students_csv')

        created, linked, errors = [], [], []
        processed_students = []  # collect User objects for bulk enrollment

        try:
            decoded  = csv_file.read().decode('utf-8-sig')
            reader   = csv.DictReader(io.StringIO(decoded))
            headers  = {(h or '').strip().lower() for h in (reader.fieldnames or [])}

            # Detect format
            nemsu_format = 'student_id' in headers and 'last_name' in headers and 'first_name' in headers
            legacy_fmt   = {'first_name', 'last_name', 'username', 'email'}.issubset(headers)

            if not nemsu_format and not legacy_fmt:
                messages.error(
                    request,
                    'Unrecognised CSV format. '
                    'Expected columns: student_id, last_name, first_name '
                    '(and optionally Middle_Initial, Course_Section).'
                )
                return redirect(next_url or 'accounts:upload_students_csv')

            for row_num, raw_row in enumerate(reader, start=2):
                # Normalise keys; skip blank column headers
                row = {k.strip().lower(): (v or '').strip()
                       for k, v in raw_row.items() if k and k.strip()}

                if nemsu_format:
                    student_id     = row.get('student_id', '')
                    last_name      = row.get('last_name', '').title()
                    first_name     = row.get('first_name', '').title()
                    middle_initial = row.get('middle_initial', '')
                    course_section = row.get('course_section', '')
                    department     = course_section
                    email          = ''
                    username       = student_id
                else:
                    username       = row.get('username', '')
                    first_name     = row.get('first_name', '')
                    last_name      = row.get('last_name', '')
                    email          = row.get('email', '')
                    student_id     = row.get('student_id', '')
                    department     = row.get('department', '')

                # Skip entirely blank rows
                if not first_name and not last_name and not student_id:
                    continue

                if not username:
                    errors.append({'row': row_num, 'reason': 'Missing student_id / username'})
                    continue

                # Account already exists — link to this instructor's roster instead of skipping
                existing = User.objects.filter(username=username, role='student').first()
                if existing:
                    existing.roster_instructors.add(request.user)
                    linked.append({'username': username,
                                   'name': existing.get_full_name() or f'{first_name} {last_name}'})
                    processed_students.append(existing)
                    continue

                # Create new account
                password = student_id if student_id else username
                user = User.objects.create_user(
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    password=password,
                    role=User.ROLE_STUDENT,
                    student_id=student_id,
                    department=department,
                    created_by=request.user,
                )
                user.roster_instructors.add(request.user)
                created.append({'username': username, 'name': user.get_full_name()})
                processed_students.append(user)

            # Auto-enroll all processed students into the target course (if provided)
            if target_course and processed_students:
                enrolled_count = 0
                for student in processed_students:
                    enrollment, was_created = Enrollment.objects.get_or_create(
                        student=student, course=target_course
                    )
                    if was_created:
                        GradeRecord.objects.get_or_create(enrollment=enrollment)
                        enrolled_count += 1
                if enrolled_count:
                    _log(request, 'enrollment_update', target=target_course.code,
                         detail=f'CSV upload enrolled {enrolled_count} student(s)')

        except Exception as exc:
            logger.error(f'CSV student upload failed: {exc}')
            messages.error(request, f'Error processing CSV: {exc}')
            return redirect(next_url or 'accounts:upload_students_csv')

        results = {'created': created, 'linked': linked, 'errors': errors}
        if created:
            messages.success(request, f'{len(created)} student account(s) created.')
        if linked:
            messages.info(request, f'{len(linked)} existing account(s) added to your roster.')
        if errors:
            messages.error(request, f'{len(errors)} row(s) had errors and were skipped.')

        if next_url:
            return redirect(next_url)

    return render(request, 'accounts/upload_students_csv.html', {'results': results})


@login_required
def create_student(request):
    """
    Instructor creates a single student account manually.
    The student can then log in with their username + auto-generated password.
    """
    if not request.user.is_instructor:
        return redirect('accounts:student_dashboard')

    if request.method == 'POST':
        form = CreateStudentForm(request.POST)
        if form.is_valid():
            student = form.save()
            password_used = (
                form.cleaned_data.get('password') or
                student.student_id or
                student.username
            )
            _log(request, 'create_student', target=student.username,
                 detail=f'Created by {request.user.username}')
            messages.success(
                request,
                f'Student account created: {student.get_full_name()} '
                f'(username: {student.username}, '
                f'default password: {password_used})'
            )
            return redirect('accounts:manage_students')
    else:
        form = CreateStudentForm()

    return render(request, 'accounts/create_student.html', {'form': form})


@login_required
def manage_students(request):
    """
    Instructor views the list of all student accounts in the system
    (so they can enroll them in courses).
    """
    if not request.user.is_instructor:
        return redirect('accounts:student_dashboard')

    search = request.GET.get('q', '').strip()
    students_qs = (User.objects
                   .filter(role=User.ROLE_STUDENT, is_superuser=False)
                   .order_by('last_name', 'first_name', 'username'))
    if search:
        students_qs = students_qs.filter(
            django_models.Q(first_name__icontains=search) |
            django_models.Q(last_name__icontains=search) |
            django_models.Q(student_id__icontains=search) |
            django_models.Q(email__icontains=search)
        )

    total_count = students_qs.count()
    paginator = Paginator(students_qs, 25)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    # JSON branch for infinite scroll / debounced search
    if request.GET.get('format') == 'json':
        from django.template.loader import render_to_string
        html = render_to_string(
            'accounts/partials/student_rows.html',
            {'students': page_obj, 'request': request},
        )
        return JsonResponse({
            'html': html,
            'has_next': page_obj.has_next(),
            'next_page': page_obj.next_page_number() if page_obj.has_next() else None,
            'total': total_count,
        })

    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'accounts/manage_students.html', {
        'students': page_obj,
        'page_obj': page_obj,
        'page_query': params.urlencode(),
        'total_count': total_count,
        'search': search,
    })


@login_required
def course_create_from_syllabus(request):
    """Edit extracted syllabus data before creating the course."""
    if not request.user.is_instructor:
        return redirect('accounts:student_dashboard')
    
    # Get pending course data from session
    pending_data = request.session.get('pending_course_data')
    if not pending_data:
        messages.error(request, 'No pending course data found. Please upload a syllabus first.')
        return redirect('accounts:syllabus_upload')
    
    if request.method == 'POST':
        # Create course with edited data (prevent duplicates)
        _code        = request.POST.get('code', '').strip()
        _semester    = request.POST.get('semester', '1st')
        _school_year = request.POST.get('school_year', '2024-2025')
        _fields = dict(
            program      = request.POST.get('program', ''),
            title        = request.POST.get('title', 'Untitled Course'),
            prerequisite = request.POST.get('prerequisite', ''),
            credit_units = request.POST.get('credit_units', ''),
            hours        = request.POST.get('hours', ''),
            block        = request.POST.get('block', ''),
            time_frame   = request.POST.get('time_frame', ''),
            description  = request.POST.get('description', ''),
            performance_target = request.POST.get('performance_target', ''),
            gad_themes   = request.POST.get('gad_themes', ''),
            clos         = pending_data.get('clos', []),
            weekly_plan  = pending_data.get('weekly_plan', []),
            raw_text     = pending_data.get('raw_text', ''),
            status       = 'draft',
        )
        if _code:
            course, _created = Course.objects.get_or_create(
                instructor=request.user,
                code=_code,
                semester=_semester,
                school_year=_school_year,
                defaults=_fields,
            )
            if not _created:
                for _k, _v in _fields.items():
                    setattr(course, _k, _v)
                course.save()
        else:
            course = Course.objects.create(
                instructor=request.user,
                code=_code,
                semester=_semester,
                school_year=_school_year,
                **_fields,
            )
        
        # Save the original file from session
        temp_path = request.session.get('syllabus_temp_path')
        temp_ext = request.session.get('syllabus_temp_ext', '.docx')
        if temp_path and os.path.exists(temp_path):
            with open(temp_path, 'rb') as f:
                course.syllabus_file.save(
                    f"syllabus_{course.pk}{temp_ext}",
                    ContentFile(f.read()),
                    save=True
                )
            _cleanup_temp_syllabus_file(request)
            request.session.pop('syllabus_temp_ext', None)
        
        # Clear session data
        if 'pending_course_data' in request.session:
            del request.session['pending_course_data']
        
        _log(request, 'create_course', target=course.code,
             detail=f'{course.title} by {request.user.username}')
        messages.success(request, f'Course created successfully: {course.code} — {course.title}')
        return redirect('accounts:course_detail', pk=course.pk)

    return render(request, 'accounts/course_edit_extracted.html', {
        'data': pending_data,
    })


# ─── Admin Portal ─────────────────────────────────────────────────────────────

def _admin_required(view_func):
    """Decorator: only superusers may access admin portal views."""
    from functools import wraps
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('accounts:login')
        if not request.user.is_superuser:
            messages.error(request, 'Admin access required.')
            return redirect('accounts:dashboard')
        return view_func(request, *args, **kwargs)
    return wrapper


@_admin_required
def portal_dashboard(request):
    """Admin portal — analytics dashboard."""
    from django.db.models.functions import TruncMonth
    from django.db.models import Count
    from grading.models import GradeRecord
    from attendance.models import AttendanceRecord

    # ── Headline stats ──────────────────────────────────────────────────────
    total_students    = User.objects.filter(role='student', is_superuser=False).count()
    total_instructors = User.objects.filter(role='instructor', is_superuser=False).count()
    total_admins      = User.objects.filter(is_superuser=True).count()
    total_courses     = Course.objects.count()
    total_enrollments = Enrollment.objects.count()

    # ── Grade distribution ──────────────────────────────────────────────────
    all_records = GradeRecord.objects.select_related('enrollment__course')
    passed_count  = sum(1 for r in all_records if r.final_grade is not None and r.passed)
    failed_count  = sum(1 for r in all_records if r.final_grade is not None and not r.passed)
    pending_count = sum(1 for r in all_records if r.final_grade is None)

    # ── Monthly new users (last 6 months) ───────────────────────────────────
    six_months_ago = timezone.now() - timedelta(days=180)
    monthly_users = (
        User.objects
        .filter(date_joined__gte=six_months_ago, is_superuser=False)
        .annotate(month=TruncMonth('date_joined'))
        .values('month', 'role')
        .annotate(count=Count('id'))
        .order_by('month')
    )
    # Build chart-ready structures
    from collections import defaultdict
    import calendar
    month_map = defaultdict(lambda: {'student': 0, 'instructor': 0})
    for row in monthly_users:
        key = row['month'].strftime('%b %Y')
        month_map[key][row['role']] = row['count']

    # Generate ordered month labels for last 6 months
    month_labels, student_data, instructor_data = [], [], []
    for i in range(5, -1, -1):
        dt = timezone.now().replace(day=1) - timedelta(days=30 * i)
        label = dt.strftime('%b %Y')
        month_labels.append(label)
        student_data.append(month_map[label]['student'])
        instructor_data.append(month_map[label]['instructor'])

    # ── Courses by program ──────────────────────────────────────────────────
    prog_counts = dict(
        Course.objects.values_list('program')
              .annotate(c=Count('id'))
              .order_by('program')
    )
    programs      = ['IT', 'CS', 'CE', '']
    prog_labels   = ['Information Technology', 'Computer Science', 'Computer Engineering', 'Unset']
    prog_values   = [prog_counts.get(p, 0) for p in programs]

    # ── Top courses by enrollment ───────────────────────────────────────────
    top_courses = (
        Course.objects.annotate(enroll_count=Count('enrollments'))
              .order_by('-enroll_count')[:8]
    )

    # ── Recent logs ─────────────────────────────────────────────────────────
    recent_logs = SystemLog.objects.select_related('actor')[:15]

    context = {
        'total_students':    total_students,
        'total_instructors': total_instructors,
        'total_admins':      total_admins,
        'total_courses':     total_courses,
        'total_enrollments': total_enrollments,
        'passed_count':      passed_count,
        'failed_count':      failed_count,
        'pending_count':     pending_count,
        'top_courses':       top_courses,
        'recent_logs':       recent_logs,
        # Chart.js JSON
        'chart_month_labels':     json.dumps(month_labels),
        'chart_student_data':     json.dumps(student_data),
        'chart_instructor_data':  json.dumps(instructor_data),
        'chart_prog_labels':      json.dumps(prog_labels),
        'chart_prog_values':      json.dumps(prog_values),
        'chart_grade_values':     json.dumps([passed_count, failed_count, pending_count]),
    }
    return render(request, 'portal/dashboard.html', context)


@_admin_required
def portal_users(request):
    """Admin portal — user list with filter."""
    role_filter = request.GET.get('role', '')
    search      = request.GET.get('q', '')

    qs = User.objects.all().order_by('role', 'last_name')
    if role_filter == 'admin':
        qs = qs.filter(is_superuser=True)
    elif role_filter:
        qs = qs.filter(role=role_filter, is_superuser=False)
    if search:
        qs = qs.filter(
            django_models.Q(username__icontains=search) |
            django_models.Q(first_name__icontains=search) |
            django_models.Q(last_name__icontains=search) |
            django_models.Q(email__icontains=search) |
            django_models.Q(student_id__icontains=search)
        )

    total_count = qs.count()
    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    params = request.GET.copy()
    params.pop('page', None)

    return render(request, 'portal/users.html', {
        'users':       page_obj,
        'page_obj':    page_obj,
        'page_query':  params.urlencode(),
        'role_filter': role_filter,
        'search':      search,
        'total_count': total_count,
    })


@_admin_required
def portal_create_user(request):
    """Admin portal — create user of any role."""
    if request.method == 'POST':
        form = CreateUserForm(request.POST)
        if form.is_valid():
            user = form.save()
            role_choice = form.cleaned_data['role_choice']
            action_map  = {
                'student':    'create_student',
                'instructor': 'create_instructor',
                'admin':      'create_admin',
            }
            _log(request, action_map.get(role_choice, 'create_student'),
                 target=user.username,
                 detail=f'Created by {request.user.username}')
            messages.success(
                request,
                f'{role_choice.title()} account created: {user.get_full_name()} ({user.username})'
            )
            return redirect('accounts:portal_users')
    else:
        form = CreateUserForm()

    return render(request, 'portal/create_user.html', {'form': form})


@_admin_required
def portal_edit_user(request, pk):
    """Admin portal — edit an existing user's profile & role."""
    target_user = get_object_or_404(User, pk=pk)

    if request.method == 'POST':
        target_user.first_name = request.POST.get('first_name', target_user.first_name).strip()
        target_user.last_name  = request.POST.get('last_name',  target_user.last_name).strip()
        target_user.email      = request.POST.get('email',      target_user.email).strip()
        target_user.department = request.POST.get('department', target_user.department).strip()
        target_user.student_id = request.POST.get('student_id', target_user.student_id).strip()
        target_user.employee_id= request.POST.get('employee_id',target_user.employee_id).strip()

        role_choice = request.POST.get('role_choice', '')
        if not target_user.is_superuser:  # never demote another superuser from here
            if role_choice == 'admin':
                target_user.is_staff     = True
                target_user.is_superuser = True
            else:
                target_user.role         = role_choice
                target_user.is_staff     = False
                target_user.is_superuser = False

        new_pw = request.POST.get('new_password', '').strip()
        if new_pw:
            target_user.set_password(new_pw)
            _log(request, 'password_change', target=target_user.username,
                 detail=f'Changed by admin {request.user.username}')

        is_active_val = request.POST.get('is_active', '')
        target_user.is_active = (is_active_val == '1')

        target_user.save()
        _log(request, 'edit_user', target=target_user.username,
             detail=f'Edited by {request.user.username}')
        messages.success(request, f'User {target_user.username} updated.')
        return redirect('accounts:portal_users')

    return render(request, 'portal/edit_user.html', {'target_user': target_user})


@_admin_required
def portal_delete_user(request, pk):
    """Admin portal — delete user."""
    target_user = get_object_or_404(User, pk=pk)
    if target_user == request.user:
        messages.error(request, 'You cannot delete your own account.')
        return redirect('accounts:portal_users')
    if request.method == 'POST':
        uname = target_user.username
        _log(request, 'delete_user', target=uname,
             detail=f'Deleted by {request.user.username}')
        target_user.delete()
        messages.success(request, f'User {uname} deleted.')
        return redirect('accounts:portal_users')
    return render(request, 'portal/delete_user.html', {'target_user': target_user})


@_admin_required
def portal_courses(request):
    """Admin portal — courses overview."""
    from django.db.models import Count
    courses = (
        Course.objects
        .annotate(enroll_count=Count('enrollments'))
        .select_related('instructor')
        .order_by('-created_at')
    )
    return render(request, 'portal/courses.html', {'courses': courses})


@_admin_required
def portal_logs(request):
    """Admin portal — system activity log."""
    action_filter = request.GET.get('action', '')
    qs = SystemLog.objects.select_related('actor')
    if action_filter:
        qs = qs.filter(action=action_filter)

    total_count = qs.count()
    paginator = Paginator(qs, 50)
    page_obj = paginator.get_page(request.GET.get('page', 1))
    params = request.GET.copy()
    params.pop('page', None)

    return render(request, 'portal/logs.html', {
        'logs':           page_obj,
        'page_obj':       page_obj,
        'page_query':     params.urlencode(),
        'action_filter':  action_filter,
        'action_choices': SystemLog.ACTION_CHOICES,
        'total_count':    total_count,
    })


@_admin_required
def portal_django_admin(request):
    """Admin portal — Django admin interface embedded in portal."""
    return render(request, 'portal/django_admin.html')


@login_required
def join_course_via_code(request):
    """Student submits a course join code to self-enroll."""
    if not request.user.is_student:
        return redirect('accounts:dashboard')
    if request.method == 'POST':
        from .models import _generate_join_code  # noqa — imported for sibling use
        code = request.POST.get('code', '').strip().upper()
        if not code:
            messages.error(request, 'Please enter a course code.')
            return redirect('accounts:student_dashboard')
        try:
            course = Course.objects.get(join_code=code, is_active=True)
        except Course.DoesNotExist:
            messages.error(request, 'Invalid course code. Please check and try again.')
            return redirect('accounts:student_dashboard')

        if Enrollment.objects.filter(student=request.user, course=course).exists():
            messages.info(request, f'You are already enrolled in {course.code} – {course.title}.')
            return redirect('accounts:student_dashboard')

        enrollment = Enrollment.objects.create(student=request.user, course=course, joined_via_code=True)
        from grading.models import GradeRecord
        GradeRecord.objects.get_or_create(enrollment=enrollment)
        messages.success(request, f'Successfully joined {course.code} – {course.title}!')
    return redirect('accounts:student_dashboard')


@login_required
def regenerate_join_code(request, pk):
    """Instructor regenerates the join code for one of their courses."""
    course = get_object_or_404(Course, pk=pk, instructor=request.user)
    if request.method == 'POST':
        from .models import _generate_join_code
        course.join_code = _generate_join_code()
        course.save(update_fields=['join_code'])
        return JsonResponse({'code': course.join_code})
    return JsonResponse({'error': 'POST required'}, status=405)


@login_required
def notifications_api(request):
    """Return recent generation items (lessons, TOS, assessments) for the current user."""
    from presentations.models import LessonPlan
    from tos.models import TableOfSpecifications
    from assessments.models import QuestionSet
    from django.urls import reverse
    from django.db.utils import ProgrammingError

    cutoff = timezone.now() - timedelta(hours=24)
    items = []

    if request.user.is_instructor:
        for lesson in LessonPlan.objects.filter(
            course__instructor=request.user,
            created_at__gte=cutoff,
        ).select_related('course').order_by('-created_at')[:15]:
            items.append({
                'key': f'lesson_{lesson.pk}',
                'type': 'lesson',
                'label': lesson.topic,
                'sub': f'{lesson.course.code} · Week {lesson.week_number}',
                'status': lesson.status,
                'error': lesson.error_msg,
                'created_at': lesson.created_at.isoformat(),
                'url': reverse('lessons:lesson_detail', kwargs={'course_pk': lesson.course.pk, 'pk': lesson.pk}),
            })

        # Use values() to avoid selecting optional/missing DB columns (e.g. weeks_covered)
        # and keep notifications API resilient when TOS migrations are out-of-sync.
        try:
            tos_rows = (
                TableOfSpecifications.objects
                .filter(course__instructor=request.user, created_at__gte=cutoff)
                .values('pk', 'exam_type', 'status', 'error_msg', 'created_at', 'course_id', 'course__code')
                .order_by('-created_at')[:10]
            )
            for tos in tos_rows:
                items.append({
                    'key': f"tos_{tos['pk']}",
                    'type': 'tos',
                    'label': f"{tos['exam_type']} TOS",
                    'sub': tos['course__code'],
                    'status': tos['status'],
                    'error': tos['error_msg'],
                    'created_at': tos['created_at'].isoformat(),
                    'url': reverse('tos:tos_detail', kwargs={'course_pk': tos['course_id'], 'pk': tos['pk']}),
                })
        except ProgrammingError:
            logger.warning('Skipping TOS notifications due to schema mismatch (missing columns).')

        for qset in QuestionSet.objects.filter(
            course__instructor=request.user,
            created_at__gte=cutoff,
        ).select_related('course').order_by('-created_at')[:10]:
            items.append({
                'key': f'assessment_{qset.pk}',
                'type': 'assessment',
                'label': qset.title,
                'sub': qset.course.code,
                'status': qset.status,
                'error': qset.error_msg,
                'created_at': qset.created_at.isoformat(),
                'url': reverse('assessments:questionset_detail', kwargs={'course_pk': qset.course.pk, 'pk': qset.pk}),
            })

        for enroll in Enrollment.objects.filter(
            course__instructor=request.user,
            joined_via_code=True,
            enrolled_at__gte=cutoff,
        ).select_related('student', 'course').order_by('-enrolled_at')[:20]:
            items.append({
                'key': f'join_{enroll.pk}',
                'type': 'student_join',
                'label': f'{enroll.student.get_full_name() or enroll.student.username} joined {enroll.course.code}',
                'sub': enroll.course.title,
                'status': 'ready',
                'error': '',
                'created_at': enroll.enrolled_at.isoformat(),
                'url': reverse('accounts:enroll_students', kwargs={'pk': enroll.course.pk}),
            })

    elif request.user.is_student:
        for enroll in Enrollment.objects.filter(
            student=request.user,
            joined_via_code=True,
            enrolled_at__gte=cutoff,
        ).select_related('course', 'course__instructor').order_by('-enrolled_at')[:10]:
            items.append({
                'key': f'join_{enroll.pk}',
                'type': 'enrollment',
                'label': f'Joined {enroll.course.code} – {enroll.course.title}',
                'sub': f'Instructor: {enroll.course.instructor.get_full_name()}',
                'status': 'ready',
                'error': '',
                'created_at': enroll.enrolled_at.isoformat(),
                'url': '',
            })

    items.sort(key=lambda x: x['created_at'], reverse=True)
    return JsonResponse({'items': items[:30]})