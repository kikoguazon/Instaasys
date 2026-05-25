import json
import logging
from functools import wraps
from datetime import date

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.db.models import Count, Q

from accounts.models import Course, Enrollment
from accounts.views import _log
from .models import AttendanceSession, AttendanceRecord
from .forms import AttendanceSessionForm

logger = logging.getLogger(__name__)


def _instructor_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_instructor:
            messages.error(request, 'Instructor access required.')
            return redirect('accounts:login')
        return view_func(request, *args, **kwargs)
    return wrapper


# ─── Attendance List ──────────────────────────────────────────────────────────

@_instructor_required
def attendance_list(request, course_pk):
    """List all attendance sessions for a course."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    sessions_qs = course.attendance_sessions.all()
    total_students = course.enrollments.count()
    total_sessions = sessions_qs.count()

    paginator = Paginator(sessions_qs, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    # JSON branch for infinite scroll
    if request.GET.get('format') == 'json':
        from django.template.loader import render_to_string
        html = render_to_string(
            'attendance/partials/session_rows.html',
            {'sessions': page_obj, 'course': course, 'request': request},
        )
        return JsonResponse({
            'html': html,
            'has_next': page_obj.has_next(),
            'next_page': page_obj.next_page_number() if page_obj.has_next() else None,
            'total': total_sessions,
        })

    params = request.GET.copy()
    params.pop('page', None)

    context = {
        'course':          course,
        'sessions':        page_obj,
        'page_obj':        page_obj,
        'page_query':      params.urlencode(),
        'total_students':  total_students,
        'total_sessions':  total_sessions,
        'form':            AttendanceSessionForm(initial={'date': date.today()}),
    }
    return render(request, 'attendance/attendance_list.html', context)


# ─── Create Session ──────────────────────────────────────────────────────────

@_instructor_required
def attendance_create(request, course_pk):
    """Create a new attendance session and mark all present by default.
    Supports both standard POST (redirect) and AJAX POST (JSON response).
    """
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if request.method == 'POST':
        form = AttendanceSessionForm(request.POST)
        if form.is_valid():
            session = form.save(commit=False)
            session.course = course
            try:
                session.save()
            except Exception:
                err = 'An attendance session already exists for that date.'
                if is_ajax:
                    return JsonResponse({'success': False, 'error': err})
                messages.error(request, err)
                return render(request, 'attendance/attendance_create.html',
                              {'form': form, 'course': course})

            # Mark all enrolled students as present by default
            enrollments = Enrollment.objects.filter(course=course)
            records = [
                AttendanceRecord(session=session, enrollment=e, status='present')
                for e in enrollments
            ]
            AttendanceRecord.objects.bulk_create(records)

            redirect_url = reverse('attendance:attendance_mark',
                                   kwargs={'course_pk': course_pk,
                                           'session_pk': session.pk})
            if is_ajax:
                return JsonResponse({'success': True, 'redirect': redirect_url})

            messages.success(request,
                f'Attendance session created for {session.date}. '
                f'{len(records)} students marked present.')
            return redirect(redirect_url)
        else:
            if is_ajax:
                return JsonResponse({'success': False,
                                     'errors': form.errors.as_json()})
    else:
        form = AttendanceSessionForm(initial={'date': date.today()})

    return render(request, 'attendance/attendance_create.html',
                  {'form': form, 'course': course})


# ─── Mark Attendance ─────────────────────────────────────────────────────────

@_instructor_required
def attendance_mark(request, course_pk, session_pk):
    """Mark/edit attendance for a specific session."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    session = get_object_or_404(AttendanceSession, pk=session_pk, course=course)

    # Ensure records exist for all enrolled students
    enrollments = Enrollment.objects.filter(course=course).select_related('student')
    existing_enrollment_ids = set(
        session.records.values_list('enrollment_id', flat=True)
    )
    new_records = [
        AttendanceRecord(session=session, enrollment=e, status='present')
        for e in enrollments if e.pk not in existing_enrollment_ids
    ]
    if new_records:
        AttendanceRecord.objects.bulk_create(new_records)

    records = (session.records
               .select_related('enrollment__student')
               .order_by('enrollment__student__last_name'))

    if request.method == 'POST':
        for record in records:
            status = request.POST.get(f'status_{record.pk}', 'present')
            if status in dict(AttendanceRecord.STATUS_CHOICES):
                record.status = status
                record.save()

        _log(request, 'attendance', target=course.code,
             detail=f'Session {session.date} marked')
        messages.success(request, f'Attendance saved for {session.date}.')
        return redirect('attendance:attendance_list', course_pk=course_pk)

    context = {
        'course': course,
        'session': session,
        'records': records,
        'status_choices': AttendanceRecord.STATUS_CHOICES,
    }
    return render(request, 'attendance/attendance_mark.html', context)


# ─── Delete Session ──────────────────────────────────────────────────────────

@_instructor_required
def attendance_delete(request, course_pk, session_pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    session = get_object_or_404(AttendanceSession, pk=session_pk, course=course)
    if request.method == 'POST':
        session.delete()
        messages.success(request, f'Attendance session for {session.date} deleted.')
        return redirect('attendance:attendance_list', course_pk=course_pk)
    return render(request, 'attendance/attendance_confirm_delete.html',
                  {'course': course, 'session': session})


# ─── Student Summary ─────────────────────────────────────────────────────────

@_instructor_required
def attendance_summary(request, course_pk):
    """Per-student attendance summary."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    enrollments = (Enrollment.objects
                   .filter(course=course)
                   .select_related('student')
                   .order_by('student__last_name'))

    total_sessions = course.attendance_sessions.count()
    summary = []
    for e in enrollments:
        records = AttendanceRecord.objects.filter(
            enrollment=e, session__course=course
        )
        present = records.filter(status='present').count()
        absent = records.filter(status='absent').count()
        late = records.filter(status='late').count()
        excused = records.filter(status='excused').count()
        pct = round((present + late) / total_sessions * 100, 1) if total_sessions else 0

        summary.append({
            'student': e.student,
            'present': present,
            'absent': absent,
            'late': late,
            'excused': excused,
            'percentage': pct,
        })

    context = {
        'course': course,
        'summary': summary,
        'total_sessions': total_sessions,
    }
    return render(request, 'attendance/attendance_summary.html', context)


# ─── Export ───────────────────────────────────────────────────────────────────

@_instructor_required
def attendance_export(request, course_pk):
    """Export attendance as plain text."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    sessions = course.attendance_sessions.order_by('date')
    enrollments = (Enrollment.objects
                   .filter(course=course)
                   .select_related('student')
                   .order_by('student__last_name'))

    lines = [
        f"ATTENDANCE REPORT — {course.code}: {course.title}",
        f"Semester: {course.get_semester_display()} S.Y. {course.school_year}",
        f"Total Sessions: {sessions.count()}",
        "=" * 80,
    ]

    # Header row
    header = f"{'No.':<4} {'Student Name':<30} "
    for s in sessions:
        header += f"{s.date.strftime('%m/%d'):<8}"
    header += f"{'%':<6}"
    lines.append(header)
    lines.append("-" * 80)

    for i, e in enumerate(enrollments, 1):
        row = f"{i:<4} {e.student.get_full_name():<30} "
        total_present = 0
        for s in sessions:
            try:
                record = AttendanceRecord.objects.get(session=s, enrollment=e)
                status_char = {
                    'present': 'P', 'absent': 'A', 'late': 'L', 'excused': 'E'
                }.get(record.status, '?')
                if record.status in ('present', 'late'):
                    total_present += 1
            except AttendanceRecord.DoesNotExist:
                status_char = '-'
            row += f"{status_char:<8}"
        pct = round(total_present / sessions.count() * 100, 1) if sessions.count() else 0
        row += f"{pct}%"
        lines.append(row)

    content = "\n".join(lines)
    response = HttpResponse(content, content_type='text/plain')
    response['Content-Disposition'] = (
        f'attachment; filename="{course.code}_attendance.txt"'
    )
    return response


# ─── Student View ─────────────────────────────────────────────────────────────

@login_required
def student_attendance(request, course_pk):
    """Student views their own attendance for a course."""
    if not request.user.is_student:
        return redirect('accounts:instructor_dashboard')

    enrollment = get_object_or_404(
        Enrollment, course_id=course_pk, student=request.user
    )
    records = (AttendanceRecord.objects
               .filter(enrollment=enrollment)
               .select_related('session')
               .order_by('-session__date'))

    total = records.count()
    present = records.filter(status='present').count()
    late = records.filter(status='late').count()
    absent = records.filter(status='absent').count()
    excused = records.filter(status='excused').count()
    pct = round((present + late) / total * 100, 1) if total else 0

    context = {
        'course': enrollment.course,
        'records': records,
        'stats': {
            'total': total,
            'present': present,
            'late': late,
            'absent': absent,
            'excused': excused,
            'percentage': pct,
        },
    }
    return render(request, 'attendance/student_attendance.html', context)
