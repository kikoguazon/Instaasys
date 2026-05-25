import json
import logging
import statistics as stats_module
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_POST
from accounts.models import Course, Enrollment
from accounts.views import _log
from .models import GradeRecord

logger = logging.getLogger(__name__)


def _instructor_required(view_func):
    from functools import wraps
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_instructor:
            return redirect('accounts:login')
        return view_func(request, *args, **kwargs)
    return wrapper


# ─── Instructor: e-Class Record (DepEd format) ────────────────────────────────

def _build_col_data(max_list, names_list, count, prefix):
    data = []
    for i in range(count):
        n    = i + 1
        mx   = max_list[i] if i < len(max_list) and max_list[i] else 10
        name = names_list[i] if i < len(names_list) and names_list[i] else f'{prefix} {n}'
        data.append({'n': n, 'max': mx, 'name': name})
    return data


def _collect_scores(post, prefix, enroll_pk, count):
    scores = []
    for n in range(1, count + 1):
        val = post.get(f'{prefix}_{enroll_pk}_{n}', '').strip()
        try:
            scores.append(float(val) if val else None)
        except ValueError:
            scores.append(None)
    while scores and scores[-1] is None:
        scores.pop()
    return scores


def _compute_stats(enrollments):
    igs = [e.grade_record.initial_grade for e in enrollments
           if hasattr(e, 'grade_record') and e.grade_record.initial_grade is not None]
    if not igs:
        return {'total': 0, 'passed': 0, 'failed': 0,
                'mean': None, 'median': None, 'sd': None, 'mps': None,
                'highest': None, 'lowest': None, 'total_score': None}
    passed = sum(1 for g in igs if g >= 75)
    return {
        'total':       len(enrollments),
        'passed':      passed,
        'failed':      len(igs) - passed,
        'passed_pct':  round(passed / len(igs) * 100, 2) if igs else 0,
        'failed_pct':  round((len(igs) - passed) / len(igs) * 100, 2) if igs else 0,
        'mean':        round(stats_module.mean(igs), 2),
        'median':      round(stats_module.median(igs), 2),
        'sd':          round(stats_module.stdev(igs), 2) if len(igs) > 1 else None,
        'mps':         round(stats_module.mean(igs), 2),
        'highest':     round(max(igs), 2),
        'lowest':      round(min(igs), 2),
        'total_score': round(sum(igs), 2),
    }


@_instructor_required
def eclass_record(request, course_pk):
    course      = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    enrollments = (Enrollment.objects
                   .filter(course=course)
                   .select_related('student', 'grade_record')
                   .order_by('student__last_name', 'student__first_name'))

    for enrollment in enrollments:
        GradeRecord.objects.get_or_create(enrollment=enrollment)

    enrollments = list(Enrollment.objects
                       .filter(course=course)
                       .select_related('student', 'grade_record')
                       .order_by('student__last_name', 'student__first_name'))

    # Determine column counts (min 1, max 10)
    ww_count = max(1, max((len(e.grade_record.quiz_scores or []) for e in enrollments), default=1))
    pt_count = max(1, max((len(e.grade_record.performance_task_scores or []) for e in enrollments), default=1))
    ao_count = max(1, max((len(e.grade_record.activity_scores or []) for e in enrollments), default=1))
    ww_count = min(ww_count, 10)
    pt_count = min(pt_count, 10)
    ao_count = min(ao_count, 10)

    if request.method == 'POST':
        def _pos(key, default=10):
            try:
                v = int(request.POST.get(key, default))
                return v if v > 0 else default
            except (ValueError, TypeError):
                return default

        # Save max scores
        course.quiz_max_scores = [_pos(f'ww_max_{n}') for n in range(1, ww_count + 1)]
        course.pt_max_scores   = [_pos(f'pt_max_{n}') for n in range(1, pt_count + 1)]
        course.activity_max_scores = [_pos(f'ao_max_{n}') for n in range(1, ao_count + 1)]
        course.requirement_max = _pos('qa_max', 10)
        course.save(update_fields=['quiz_max_scores', 'pt_max_scores', 'activity_max_scores', 'requirement_max'])

        # Shared column names
        ww_names = [request.POST.get(f'ww_name_{n}', f'WW {n}').strip() or f'WW {n}'
                    for n in range(1, ww_count + 1)]
        pt_names = [request.POST.get(f'pt_name_{n}', f'PT {n}').strip() or f'PT {n}'
                    for n in range(1, pt_count + 1)]
        ao_names = [request.POST.get(f'ao_name_{n}', f'AO {n}').strip() or f'AO {n}'
                    for n in range(1, ao_count + 1)]

        def _float(key):
            val = request.POST.get(key, '').strip()
            try:
                return float(val) if val else None
            except ValueError:
                return None

        for e in enrollments:
            rec = e.grade_record
            rec.quiz_scores            = _collect_scores(request.POST, 'ww', e.pk, ww_count)
            rec.performance_task_scores = _collect_scores(request.POST, 'pt', e.pk, pt_count)
            rec.activity_scores        = _collect_scores(request.POST, 'ao', e.pk, ao_count)
            rec.requirement_score      = _float(f'qa_{e.pk}')
            rec.quiz_column_names      = ww_names
            rec.pt_column_names        = pt_names
            rec.activity_column_names  = ao_names
            rec.remarks                = request.POST.get(f'remarks_{e.pk}', '').strip()
            rec.save()

        _log(request, 'grade_update', target=course.code, detail='E-class record updated')
        messages.success(request, 'Grades saved.')
        return redirect('grading:eclass_record', course_pk=course_pk)

    # Build column metadata
    first_rec  = enrollments[0].grade_record if enrollments else None
    ww_col_data = _build_col_data(
        course.quiz_max_scores or [], first_rec.quiz_column_names if first_rec else [],
        ww_count, 'WW')
    pt_col_data = _build_col_data(
        course.pt_max_scores or [], first_rec.pt_column_names if first_rec else [],
        pt_count, 'PT')
    ao_col_data = _build_col_data(
        course.activity_max_scores or [], first_rec.activity_column_names if first_rec else [],
        ao_count, 'AO')

    # Serialize scores for JS
    ww_json = json.dumps({str(e.pk): list(e.grade_record.quiz_scores or []) for e in enrollments})
    pt_json = json.dumps({str(e.pk): list(e.grade_record.performance_task_scores or []) for e in enrollments})
    ao_json = json.dumps({str(e.pk): list(e.grade_record.activity_scores or []) for e in enrollments})

    context = {
        'course':       course,
        'enrollments':  enrollments,
        'ww_col_data':  ww_col_data,
        'pt_col_data':  pt_col_data,
        'ao_col_data':  ao_col_data,
        'ww_count':     ww_count,
        'pt_count':     pt_count,
        'ao_count':     ao_count,
        'ww_json':      ww_json,
        'pt_json':      pt_json,
        'ao_json':      ao_json,
        'stats':        _compute_stats(enrollments),
    }
    return render(request, 'grading/eclass_record.html', context)


@_instructor_required
def add_ww_column(request, course_pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    enrollments = Enrollment.objects.filter(course=course).select_related('grade_record')
    for e in enrollments:
        rec = e.grade_record
        n   = len(rec.quiz_scores or []) + 1
        rec.quiz_scores       = list(rec.quiz_scores or []) + [None]
        rec.quiz_column_names = list(rec.quiz_column_names or []) + [f'CS{n}']
        rec.save()
    return redirect('grading:eclass_record', course_pk=course_pk)


@_instructor_required
def add_pt_column(request, course_pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    enrollments = Enrollment.objects.filter(course=course).select_related('grade_record')
    for e in enrollments:
        rec = e.grade_record
        n   = len(rec.performance_task_scores or []) + 1
        rec.performance_task_scores = list(rec.performance_task_scores or []) + [None]
        rec.pt_column_names         = list(rec.pt_column_names or []) + [f'PT{n}']
        rec.save()
    return redirect('grading:eclass_record', course_pk=course_pk)


@_instructor_required
def add_activity_column(request, course_pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    enrollments = Enrollment.objects.filter(course=course).select_related('grade_record')
    for e in enrollments:
        rec = e.grade_record
        n   = len(rec.activity_scores or []) + 1
        rec.activity_scores       = list(rec.activity_scores or []) + [None]
        rec.activity_column_names = list(rec.activity_column_names or []) + [f'AO{n}']
        rec.save()
    return redirect('grading:eclass_record', course_pk=course_pk)


@_instructor_required
def delete_ww_column(request, course_pk, col_num):
    """Delete a CS (Written Work) column."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    enrollments = Enrollment.objects.filter(course=course).select_related('grade_record')
    
    col_index = col_num - 1  # Convert to 0-based index
    
    for e in enrollments:
        rec = e.grade_record
        scores = list(rec.quiz_scores or [])
        names = list(rec.quiz_column_names or [])
        
        # Remove the column if it exists
        if col_index < len(scores):
            scores.pop(col_index)
        if col_index < len(names):
            names.pop(col_index)
        
        rec.quiz_scores = scores
        rec.quiz_column_names = names
        rec.save()
    
    messages.success(request, f'CS column {col_num} deleted successfully.')
    return redirect('grading:eclass_record', course_pk=course_pk)


@_instructor_required
def delete_pt_column(request, course_pk, col_num):
    """Delete a PT (Performance Task) column."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    enrollments = Enrollment.objects.filter(course=course).select_related('grade_record')

    col_index = col_num - 1  # Convert to 0-based index

    for e in enrollments:
        rec = e.grade_record
        scores = list(rec.performance_task_scores or [])
        names = list(rec.pt_column_names or [])

        # Remove the column if it exists
        if col_index < len(scores):
            scores.pop(col_index)
        if col_index < len(names):
            names.pop(col_index)

        rec.performance_task_scores = scores
        rec.pt_column_names = names
        rec.save()

    messages.success(request, f'PT column {col_num} deleted successfully.')
    return redirect('grading:eclass_record', course_pk=course_pk)


@_instructor_required
def delete_activity_column(request, course_pk, col_num):
    """Delete an AO (Activity Output) column."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    enrollments = Enrollment.objects.filter(course=course).select_related('grade_record')

    col_index = col_num - 1  # Convert to 0-based index

    for e in enrollments:
        rec = e.grade_record
        scores = list(rec.activity_scores or [])
        names = list(rec.activity_column_names or [])

        # Remove the column if it exists
        if col_index < len(scores):
            scores.pop(col_index)
        if col_index < len(names):
            names.pop(col_index)

        rec.activity_scores = scores
        rec.activity_column_names = names
        rec.save()

    messages.success(request, f'AO column {col_num} deleted successfully.')
    return redirect('grading:eclass_record', course_pk=course_pk)


@_instructor_required
def delete_final_cs_column(request, course_pk, col_num):
    """Delete a Final CS column."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    enrollments = Enrollment.objects.filter(course=course).select_related('grade_record')
    col_index = col_num - 1
    # Also remove from course max scores
    max_scores = list(course.final_cs_max_scores or [])
    if col_index < len(max_scores):
        max_scores.pop(col_index)
    course.final_cs_max_scores = max_scores
    course.save(update_fields=['final_cs_max_scores'])
    for e in enrollments:
        rec = e.grade_record
        scores = list(rec.final_cs_scores or [])
        names  = list(rec.final_cs_column_names or [])
        if col_index < len(scores): scores.pop(col_index)
        if col_index < len(names):  names.pop(col_index)
        rec.final_cs_scores       = scores
        rec.final_cs_column_names = names
        rec.save()
    messages.success(request, f'Final CS column {col_num} deleted.')
    return redirect('grading:midterm_sheet', course_pk=course_pk)


@_instructor_required
def delete_final_pt_column(request, course_pk, col_num):
    """Delete a Final PT column."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    enrollments = Enrollment.objects.filter(course=course).select_related('grade_record')
    col_index = col_num - 1
    max_scores = list(course.final_pt_max_scores or [])
    if col_index < len(max_scores):
        max_scores.pop(col_index)
    course.final_pt_max_scores = max_scores
    course.save(update_fields=['final_pt_max_scores'])
    for e in enrollments:
        rec = e.grade_record
        scores = list(rec.final_pt_scores or [])
        names  = list(rec.final_pt_column_names or [])
        if col_index < len(scores): scores.pop(col_index)
        if col_index < len(names):  names.pop(col_index)
        rec.final_pt_scores       = scores
        rec.final_pt_column_names = names
        rec.save()
    messages.success(request, f'Final PT column {col_num} deleted.')
    return redirect('grading:midterm_sheet', course_pk=course_pk)


@_instructor_required
def delete_final_activity_column(request, course_pk, col_num):
    """Delete a Final AO (Activity Output) column."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    enrollments = Enrollment.objects.filter(course=course).select_related('grade_record')
    col_index = col_num - 1
    max_scores = list(course.final_activity_max_scores or [])
    if col_index < len(max_scores):
        max_scores.pop(col_index)
    course.final_activity_max_scores = max_scores
    course.save(update_fields=['final_activity_max_scores'])
    for e in enrollments:
        rec = e.grade_record
        scores = list(rec.final_activity_scores or [])
        names  = list(rec.final_activity_column_names or [])
        if col_index < len(scores): scores.pop(col_index)
        if col_index < len(names):  names.pop(col_index)
        rec.final_activity_scores = scores
        rec.final_activity_column_names = names
        rec.save()
    messages.success(request, f'Final AO column {col_num} deleted.')
    return redirect('grading:midterm_sheet', course_pk=course_pk)


@_instructor_required
@require_POST
def final_autosave_score(request, course_pk):
    """AJAX autosave for Final sheet — column names and HPS."""
    try:
        course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
        field_name = request.POST.get('field_name', '')
        value      = request.POST.get('value', '').strip()

        # Score updates (individual student records)
        enrollment_id = request.POST.get('enrollment_id')
        if enrollment_id and (field_name.startswith('fcs_') or field_name.startswith('fpt_') or
                               field_name.startswith('fao_') or field_name == 'fexam' or
                               field_name == 'fin_score' or field_name == 'remarks'):
            try:
                enrollment = Enrollment.objects.get(pk=enrollment_id, course=course)
                rec = enrollment.grade_record

                if field_name.startswith('fcs_'):
                    col_num = int(field_name.split('_')[-1]) - 1
                    scores = list(rec.final_cs_scores or [])
                    while len(scores) <= col_num:
                        scores.append(None)
                    try:
                        scores[col_num] = float(value) if value else None
                    except ValueError:
                        scores[col_num] = None
                    rec.final_cs_scores = scores
                    rec.save(update_fields=['final_cs_scores'])
                elif field_name.startswith('fpt_'):
                    col_num = int(field_name.split('_')[-1]) - 1
                    scores = list(rec.final_pt_scores or [])
                    while len(scores) <= col_num:
                        scores.append(None)
                    try:
                        scores[col_num] = float(value) if value else None
                    except ValueError:
                        scores[col_num] = None
                    rec.final_pt_scores = scores
                    rec.save(update_fields=['final_pt_scores'])
                elif field_name.startswith('fao_'):
                    col_num = int(field_name.split('_')[-1]) - 1
                    scores = list(rec.final_activity_scores or [])
                    while len(scores) <= col_num:
                        scores.append(None)
                    try:
                        scores[col_num] = float(value) if value else None
                    except ValueError:
                        scores[col_num] = None
                    rec.final_activity_scores = scores
                    rec.save(update_fields=['final_activity_scores'])
                elif field_name == 'fexam':
                    try:
                        rec.final_exam_score = float(value) if value else None
                    except ValueError:
                        rec.final_exam_score = None
                    rec.save(update_fields=['final_exam_score'])
                elif field_name == 'fin_score':
                    try:
                        rec.final_score = float(value) if value else None
                    except ValueError:
                        rec.final_score = None
                    rec.save(update_fields=['final_score'])
                elif field_name == 'remarks':
                    rec.remarks = value
                    rec.save(update_fields=['remarks'])

                return JsonResponse({'success': True, 'field_name': field_name, 'value': value})
            except Enrollment.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Enrollment not found'}, status=404)

        # Column name updates
        if '_name_' in field_name:
            enrollments = Enrollment.objects.filter(course=course).select_related('grade_record')
            if field_name.startswith('fcs_name_'):
                col_num = int(field_name.split('_')[-1]) - 1
                for e in enrollments:
                    rec   = e.grade_record
                    names = list(rec.final_cs_column_names or [])
                    while len(names) <= col_num:
                        names.append(f'CS {len(names) + 1}')
                    names[col_num] = value or f'CS {col_num + 1}'
                    rec.final_cs_column_names = names
                    rec.save()
            elif field_name.startswith('fpt_name_'):
                col_num = int(field_name.split('_')[-1]) - 1
                for e in enrollments:
                    rec   = e.grade_record
                    names = list(rec.final_pt_column_names or [])
                    while len(names) <= col_num:
                        names.append(f'PT {len(names) + 1}')
                    names[col_num] = value or f'PT {col_num + 1}'
                    rec.final_pt_column_names = names
                    rec.save()
            elif field_name.startswith('fao_name_'):
                col_num = int(field_name.split('_')[-1]) - 1
                for e in enrollments:
                    rec   = e.grade_record
                    names = list(rec.final_activity_column_names or [])
                    while len(names) <= col_num:
                        names.append(f'AO {len(names) + 1}')
                    names[col_num] = value or f'AO {col_num + 1}'
                    rec.final_activity_column_names = names
                    rec.save()
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        # HPS updates (course-level)
        if field_name.startswith('fcs_max_'):
            col_num = int(field_name.split('_')[-1]) - 1
            maxes   = list(course.final_cs_max_scores or [])
            while len(maxes) <= col_num:
                maxes.append(10)
            try:
                maxes[col_num] = int(value) if value else 10
            except ValueError:
                maxes[col_num] = 10
            course.final_cs_max_scores = maxes
            course.save(update_fields=['final_cs_max_scores'])
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        if field_name.startswith('fpt_max_'):
            col_num = int(field_name.split('_')[-1]) - 1
            maxes   = list(course.final_pt_max_scores or [])
            while len(maxes) <= col_num:
                maxes.append(10)
            try:
                maxes[col_num] = int(value) if value else 10
            except ValueError:
                maxes[col_num] = 10
            course.final_pt_max_scores = maxes
            course.save(update_fields=['final_pt_max_scores'])
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        if field_name.startswith('fao_max_'):
            col_num = int(field_name.split('_')[-1]) - 1
            maxes   = list(course.final_activity_max_scores or [])
            while len(maxes) <= col_num:
                maxes.append(10)
            try:
                maxes[col_num] = int(value) if value else 10
            except ValueError:
                maxes[col_num] = 10
            course.final_activity_max_scores = maxes
            course.save(update_fields=['final_activity_max_scores'])
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        if field_name == 'fexam_max':
            try:
                course.final_exam_max = int(value) if value else 100
            except ValueError:
                course.final_exam_max = 100
            course.save(update_fields=['final_exam_max'])
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        # Weight updates
        if field_name == 'cs_weight':
            try:
                course.cs_weight = int(value) if value else 20
            except ValueError:
                course.cs_weight = 20
            course.save(update_fields=['cs_weight'])
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        if field_name == 'req_weight':
            try:
                course.req_weight = int(value) if value else 20
            except ValueError:
                course.req_weight = 20
            course.save(update_fields=['req_weight'])
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        if field_name == 'ao_weight':
            try:
                course.ao_weight = int(value) if value else 20
            except ValueError:
                course.ao_weight = 20
            course.save(update_fields=['ao_weight'])
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        if field_name == 'exam_weight':
            try:
                course.exam_weight = int(value) if value else 40
            except ValueError:
                course.exam_weight = 40
            course.save(update_fields=['exam_weight'])
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        # Section name updates
        if field_name == 'cs_section_name':
            course.cs_section_name = value
            course.save(update_fields=['cs_section_name'])
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        if field_name == 'pt_section_name':
            course.pt_section_name = value
            course.save(update_fields=['pt_section_name'])
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        if field_name == 'ao_section_name':
            course.ao_section_name = value
            course.save(update_fields=['ao_section_name'])
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        if field_name == 'exam_section_name':
            course.exam_section_name = value
            course.save(update_fields=['exam_section_name'])
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        return JsonResponse({'success': False, 'error': 'Unknown field'}, status=400)
    except Exception as exc:
        logger.error(f'final_autosave_score error: {exc}')
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@_instructor_required
def add_final_cs_column(request, course_pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    enrollments = Enrollment.objects.filter(course=course).select_related('grade_record')
    for e in enrollments:
        rec = e.grade_record
        n   = len(rec.final_cs_scores or []) + 1
        rec.final_cs_scores       = list(rec.final_cs_scores or []) + [None]
        prefix = course.cs_section_name.strip() or 'Class Standing'
        rec.final_cs_column_names = list(rec.final_cs_column_names or []) + [f'{prefix} {n}']
        rec.save()
    return redirect('grading:midterm_sheet', course_pk=course_pk)


@_instructor_required
def add_final_pt_column(request, course_pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    enrollments = Enrollment.objects.filter(course=course).select_related('grade_record')
    for e in enrollments:
        rec = e.grade_record
        n   = len(rec.final_pt_scores or []) + 1
        rec.final_pt_scores       = list(rec.final_pt_scores or []) + [None]
        prefix = course.pt_section_name.strip() or 'Performance Task'
        rec.final_pt_column_names = list(rec.final_pt_column_names or []) + [f'{prefix} {n}']
        rec.save()
    return redirect('grading:midterm_sheet', course_pk=course_pk)


@_instructor_required
def add_final_activity_column(request, course_pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    enrollments = Enrollment.objects.filter(course=course).select_related('grade_record')
    for e in enrollments:
        rec = e.grade_record
        n   = len(rec.final_activity_scores or []) + 1
        rec.final_activity_scores       = list(rec.final_activity_scores or []) + [None]
        prefix = course.ao_section_name.strip() or 'Activity Output'
        rec.final_activity_column_names = list(rec.final_activity_column_names or []) + [f'{prefix} {n}']
        rec.save()
    return redirect('grading:midterm_sheet', course_pk=course_pk)


@_instructor_required
def midterm_sheet(request, course_pk):
    """Final term full spreadsheet (CS 20%, PT 40%, Major Exams 40%)."""
    course      = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    enrollments = (Enrollment.objects
                   .filter(course=course)
                   .select_related('student', 'grade_record')
                   .order_by('student__last_name', 'student__first_name'))

    for enrollment in enrollments:
        GradeRecord.objects.get_or_create(enrollment=enrollment)

    enrollments = list(Enrollment.objects
                       .filter(course=course)
                       .select_related('student', 'grade_record')
                       .order_by('student__last_name', 'student__first_name'))

    # Determine column counts
    fcs_count = max(1, max((len(e.grade_record.final_cs_scores or []) for e in enrollments), default=1))
    fpt_count = max(1, max((len(e.grade_record.final_pt_scores or []) for e in enrollments), default=1))
    fao_count = max(1, max((len(e.grade_record.final_activity_scores or []) for e in enrollments), default=1))
    fcs_count = min(fcs_count, 10)
    fpt_count = min(fpt_count, 10)
    fao_count = min(fao_count, 10)

    if request.method == 'POST':
        def _pos(key, default=10):
            try:
                v = int(request.POST.get(key, default))
                return v if v > 0 else default
            except (ValueError, TypeError):
                return default

        course.final_cs_max_scores = [_pos(f'fcs_max_{n}') for n in range(1, fcs_count + 1)]
        course.final_pt_max_scores = [_pos(f'fpt_max_{n}') for n in range(1, fpt_count + 1)]
        course.final_activity_max_scores = [_pos(f'fao_max_{n}') for n in range(1, fao_count + 1)]
        course.final_exam_max = _pos('fexam_max', 100)
        course.save(update_fields=['final_cs_max_scores', 'final_pt_max_scores', 'final_activity_max_scores', 'final_exam_max'])

        fcs_names = [request.POST.get(f'fcs_name_{n}', f'CS {n}').strip() or f'CS {n}'
                     for n in range(1, fcs_count + 1)]
        fpt_names = [request.POST.get(f'fpt_name_{n}', f'PT {n}').strip() or f'PT {n}'
                     for n in range(1, fpt_count + 1)]
        fao_names = [request.POST.get(f'fao_name_{n}', f'AO {n}').strip() or f'AO {n}'
                     for n in range(1, fao_count + 1)]

        def _float(key):
            val = request.POST.get(key, '').strip()
            try:
                return float(val) if val else None
            except ValueError:
                return None

        for e in enrollments:
            rec = e.grade_record
            rec.final_cs_scores       = _collect_scores(request.POST, 'fcs', e.pk, fcs_count)
            rec.final_pt_scores       = _collect_scores(request.POST, 'fpt', e.pk, fpt_count)
            rec.final_activity_scores = _collect_scores(request.POST, 'fao', e.pk, fao_count)
            rec.final_exam_score      = _float(f'fexam_{e.pk}')
            rec.final_cs_column_names = fcs_names
            rec.final_pt_column_names = fpt_names
            rec.final_activity_column_names = fao_names
            rec.save()

        _log(request, 'grade_update', target=course.code, detail='Final e-class record updated')
        messages.success(request, 'Final grades saved.')
        return redirect('grading:midterm_sheet', course_pk=course_pk)

    first_rec   = enrollments[0].grade_record if enrollments else None
    cs_col_data = _build_col_data(
        course.final_cs_max_scores or [],
        first_rec.final_cs_column_names if first_rec else [],
        fcs_count, 'CS')
    pt_col_data = _build_col_data(
        course.final_pt_max_scores or [],
        first_rec.final_pt_column_names if first_rec else [],
        fpt_count, 'PT')
    ao_col_data = _build_col_data(
        course.final_activity_max_scores or [],
        first_rec.final_activity_column_names if first_rec else [],
        fao_count, 'AO')

    fcs_json = json.dumps({str(e.pk): list(e.grade_record.final_cs_scores or []) for e in enrollments})
    fpt_json = json.dumps({str(e.pk): list(e.grade_record.final_pt_scores or []) for e in enrollments})
    fao_json = json.dumps({str(e.pk): list(e.grade_record.final_activity_scores or []) for e in enrollments})

    context = {
        'course':      course,
        'enrollments': enrollments,
        'cs_col_data': cs_col_data,
        'pt_col_data': pt_col_data,
        'ao_col_data': ao_col_data,
        'fcs_count':   fcs_count,
        'fpt_count':   fpt_count,
        'fao_count':   fao_count,
        'fcs_json':    fcs_json,
        'fpt_json':    fpt_json,
        'fao_json':    fao_json,
        'stats':       _compute_stats(enrollments),
    }
    return render(request, 'grading/midterm_sheet.html', context)


@_instructor_required
def final_sheet(request, course_pk):
    """Separate sheet for final grades."""
    course      = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    enrollments = (Enrollment.objects
                   .filter(course=course)
                   .select_related('student', 'grade_record')
                   .order_by('student__last_name', 'student__first_name'))

    # Ensure a GradeRecord exists for every enrollment
    for enrollment in enrollments:
        GradeRecord.objects.get_or_create(enrollment=enrollment)

    # Re-fetch after get_or_create
    enrollments = (Enrollment.objects
                   .filter(course=course)
                   .select_related('student', 'grade_record')
                   .order_by('student__last_name', 'student__first_name'))

    if request.method == 'POST':
        for enrollment in enrollments:
            rec = enrollment.grade_record
            
            def _float_or_none(key):
                val = request.POST.get(key, '').strip()
                try:
                    return float(val) if val else None
                except ValueError:
                    return None

            rec.final_score = _float_or_none(f'fin_{enrollment.pk}')
            rec.remarks = request.POST.get(f'remarks_{enrollment.pk}', '').strip()
            rec.save()

        messages.success(request, 'Final grades saved successfully.')
        return redirect('grading:final_sheet', course_pk=course_pk)

    context = {
        'course':       course,
        'enrollments':  enrollments,
    }
    return render(request, 'grading/final_sheet.html', context)


@_instructor_required
def add_quiz_column(request, course_pk):
    """AJAX-free: redirect back with one more column."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    enrollments = Enrollment.objects.filter(course=course).select_related('grade_record')

    # Get the first enrollment to determine the next column number
    first_enrollment = enrollments.first()
    if first_enrollment:
        rec = first_enrollment.grade_record
        current_count = len(rec.quiz_scores) if rec.quiz_scores else 0
        new_column_name = f"Quiz {current_count + 1}"
        
        for enrollment in enrollments:
            rec = enrollment.grade_record
            rec.quiz_scores = list(rec.quiz_scores) + [None]
            rec.quiz_column_names = list(rec.quiz_column_names) + [new_column_name]
            rec.save()

    return redirect('grading:eclass_record', course_pk=course_pk)


@_instructor_required
def grade_summary(request, course_pk):
    """Grade summary with automatic computation using attendance + assessment scores."""
    from attendance.models import AttendanceSession, AttendanceRecord

    course      = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    enrollments = list(Enrollment.objects
                       .filter(course=course)
                       .select_related('student', 'grade_record')
                       .order_by('student__last_name', 'student__first_name'))

    # Get total sessions for attendance calculation
    total_sessions = AttendanceSession.objects.filter(course=course).count()

    # Helper functions for grade computation
    def calc_pct(scores, max_scores):
        """Calculate percentage from list of scores and max scores."""
        if not scores or not max_scores:
            return None
        valid_scores = [s for s in scores if s is not None]
        if not valid_scores:
            return None
        valid_maxes = [max_scores[i] if i < len(max_scores) and max_scores[i] else 10
                       for i in range(len(valid_scores))]
        total = sum(valid_scores)
        max_total = sum(valid_maxes)
        return (total / max_total * 100) if max_total else None

    def calc_score_pct(score, max_val):
        """Calculate percentage from single score."""
        if score is None or max_val is None or max_val == 0:
            return None
        return (score / max_val) * 100

    def calc_attendance_pct(enrollment):
        """Calculate attendance percentage for an enrollment."""
        if total_sessions == 0:
            return 0
        present_count = AttendanceRecord.objects.filter(
            enrollment=enrollment, status__in=['present', 'late']
        ).count()
        return (present_count / total_sessions) * 100

    def calc_cs_pct(att_pct, cs_pct):
        """Calculate Class Standing percentage: (attendance 1/3 + cs_score 2/3)."""
        if cs_pct is None:
            return None
        return (att_pct * (1/3)) + (cs_pct * (2/3))

    def calc_initial_grade(cs_pct, pt_pct, ao_pct, exam_pct, course_obj):
        """Calculate initial grade using weighted percentages."""
        if any(v is None for v in [cs_pct, pt_pct, ao_pct, exam_pct]):
            return None
        cs_w = (course_obj.cs_weight or 20) / 100
        pt_w = (course_obj.req_weight or 20) / 100
        ao_w = (course_obj.ao_weight or 20) / 100
        exam_w = (course_obj.exam_weight or 40) / 100
        return (cs_pct * cs_w) + (pt_pct * pt_w) + (ao_pct * ao_w) + (exam_pct * exam_w)

    def calc_term_grade(initial_grade):
        """Apply CHED transmutation formula: 60 + (IG × 0.4)."""
        if initial_grade is None:
            return None
        return 60 + (initial_grade * 0.4)

    # Compute grades for each enrollment
    summary_rows = []
    passed_count = 0
    failed_count = 0

    for e in enrollments:
        rec = e.grade_record
        att_pct = calc_attendance_pct(e)

        # Midterm term computation
        cs_pct_mid = calc_cs_pct(att_pct, calc_pct(rec.quiz_scores, course.quiz_max_scores))
        pt_pct_mid = calc_pct(rec.performance_task_scores, course.pt_max_scores)
        ao_pct_mid = calc_pct(rec.activity_scores, course.activity_max_scores)
        exam_pct_mid = calc_score_pct(rec.requirement_score, course.requirement_max or 10)

        ig_mid = calc_initial_grade(cs_pct_mid, pt_pct_mid, ao_pct_mid, exam_pct_mid, course)
        tg_mid = calc_term_grade(ig_mid)

        # Final term computation
        cs_pct_fin = calc_cs_pct(att_pct, calc_pct(rec.final_cs_scores, course.final_cs_max_scores))
        pt_pct_fin = calc_pct(rec.final_pt_scores, course.final_pt_max_scores)
        ao_pct_fin = calc_pct(rec.final_activity_scores, course.final_activity_max_scores)
        exam_pct_fin = calc_score_pct(rec.final_exam_score, course.final_exam_max or 100)

        ig_fin = calc_initial_grade(cs_pct_fin, pt_pct_fin, ao_pct_fin, exam_pct_fin, course)
        tg_fin = calc_term_grade(ig_fin)

        # Final Semestral Grade
        fsg = None
        if tg_mid is not None and tg_fin is not None:
            fsg = (tg_mid + tg_fin) / 2

        passed = fsg is not None and fsg >= 75
        if passed:
            passed_count += 1
        elif fsg is not None:
            failed_count += 1

        summary_rows.append({
            'enrollment': e,
            'att_pct': round(att_pct, 1),
            # Midterm breakdown
            'cs_mid': round(cs_pct_mid, 1) if cs_pct_mid is not None else None,
            'pt_mid': round(pt_pct_mid, 1) if pt_pct_mid is not None else None,
            'ao_mid': round(ao_pct_mid, 1) if ao_pct_mid is not None else None,
            'exam_mid': round(exam_pct_mid, 1) if exam_pct_mid is not None else None,
            'ig_mid': round(ig_mid, 2) if ig_mid is not None else None,
            'tg_mid': round(tg_mid, 2) if tg_mid is not None else None,
            # Final breakdown
            'cs_fin': round(cs_pct_fin, 1) if cs_pct_fin is not None else None,
            'pt_fin': round(pt_pct_fin, 1) if pt_pct_fin is not None else None,
            'ao_fin': round(ao_pct_fin, 1) if ao_pct_fin is not None else None,
            'exam_fin': round(exam_pct_fin, 1) if exam_pct_fin is not None else None,
            'ig_fin': round(ig_fin, 2) if ig_fin is not None else None,
            'tg_fin': round(tg_fin, 2) if tg_fin is not None else None,
            # Final Semestral Grade
            'fsg': round(fsg, 2) if fsg is not None else None,
            'passed': passed,
        })

    # Calculate class average
    fsg_values = [row['fsg'] for row in summary_rows if row['fsg'] is not None]
    class_avg = sum(fsg_values) / len(fsg_values) if fsg_values else None

    context = {
        'course':        course,
        'enrollments':   enrollments,
        'summary_rows':  summary_rows,
        'total':         len(enrollments),
        'passed':        passed_count,
        'failed':        failed_count,
        'class_avg':     round(class_avg, 2) if class_avg is not None else None,
        'total_sessions': total_sessions,
    }
    return render(request, 'grading/grade_summary.html', context)


@_instructor_required
@require_POST
def autosave_score(request, course_pk):
    """Auto-save a single score or column name via AJAX."""
    try:
        course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
        
        enrollment_id = request.POST.get('enrollment_id')
        field_name = request.POST.get('field_name')  # e.g., 'ww_1', 'pt_2', 'qa', 'ww_name_1'
        value = request.POST.get('value', '').strip()
        
        # Handle column name updates (applies to all students)
        if '_name_' in field_name:
            # This is a column name update
            enrollments = Enrollment.objects.filter(course=course).select_related('grade_record')

            if field_name.startswith('ww_name_'):
                col_num = int(field_name.split('_')[-1]) - 1
                for enrollment in enrollments:
                    rec = enrollment.grade_record
                    names = list(rec.quiz_column_names or [])
                    while len(names) <= col_num:
                        names.append(f'CS{len(names) + 1}')
                    names[col_num] = value or f'CS{col_num + 1}'
                    rec.quiz_column_names = names
                    rec.save()

            elif field_name.startswith('pt_name_'):
                col_num = int(field_name.split('_')[-1]) - 1
                for enrollment in enrollments:
                    rec = enrollment.grade_record
                    names = list(rec.pt_column_names or [])
                    while len(names) <= col_num:
                        names.append(f'PT{len(names) + 1}')
                    names[col_num] = value or f'PT{col_num + 1}'
                    rec.pt_column_names = names
                    rec.save()

            elif field_name.startswith('ao_name_'):
                col_num = int(field_name.split('_')[-1]) - 1
                for enrollment in enrollments:
                    rec = enrollment.grade_record
                    names = list(rec.activity_column_names or [])
                    while len(names) <= col_num:
                        names.append(f'AO{len(names) + 1}')
                    names[col_num] = value or f'AO{col_num + 1}'
                    rec.activity_column_names = names
                    rec.save()

            return JsonResponse({
                'success': True,
                'message': 'Column name saved',
                'field_name': field_name,
                'value': value
            })

        # Handle HPS (max score) updates — course-level
        if field_name.startswith('ww_max_'):
            col_num = int(field_name.split('_')[-1]) - 1
            maxes = list(course.quiz_max_scores or [])
            while len(maxes) <= col_num:
                maxes.append(10)
            try:
                maxes[col_num] = int(value) if value else 10
            except ValueError:
                maxes[col_num] = 10
            course.quiz_max_scores = maxes
            course.save(update_fields=['quiz_max_scores'])
            return JsonResponse({'success': True, 'field_name': field_name})

        if field_name.startswith('pt_max_'):
            col_num = int(field_name.split('_')[-1]) - 1
            maxes = list(course.pt_max_scores or [])
            while len(maxes) <= col_num:
                maxes.append(10)
            try:
                maxes[col_num] = int(value) if value else 10
            except ValueError:
                maxes[col_num] = 10
            course.pt_max_scores = maxes
            course.save(update_fields=['pt_max_scores'])
            return JsonResponse({'success': True, 'field_name': field_name})

        if field_name.startswith('ao_max_'):
            col_num = int(field_name.split('_')[-1]) - 1
            maxes = list(course.activity_max_scores or [])
            while len(maxes) <= col_num:
                maxes.append(10)
            try:
                maxes[col_num] = int(value) if value else 10
            except ValueError:
                maxes[col_num] = 10
            course.activity_max_scores = maxes
            course.save(update_fields=['activity_max_scores'])
            return JsonResponse({'success': True, 'field_name': field_name})

        if field_name == 'qa_max':
            try:
                course.requirement_max = int(value) if value else 10
            except ValueError:
                course.requirement_max = 10
            course.save(update_fields=['requirement_max'])
            return JsonResponse({'success': True, 'field_name': field_name})

        # Weight updates
        if field_name == 'cs_weight':
            try:
                course.cs_weight = int(value) if value else 20
            except ValueError:
                course.cs_weight = 20
            course.save(update_fields=['cs_weight'])
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        if field_name == 'req_weight':
            try:
                course.req_weight = int(value) if value else 20
            except ValueError:
                course.req_weight = 20
            course.save(update_fields=['req_weight'])
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        if field_name == 'ao_weight':
            try:
                course.ao_weight = int(value) if value else 20
            except ValueError:
                course.ao_weight = 20
            course.save(update_fields=['ao_weight'])
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        if field_name == 'exam_weight':
            try:
                course.exam_weight = int(value) if value else 40
            except ValueError:
                course.exam_weight = 40
            course.save(update_fields=['exam_weight'])
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        # Section name updates
        if field_name == 'cs_section_name':
            course.cs_section_name = value
            course.save(update_fields=['cs_section_name'])
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        if field_name == 'pt_section_name':
            course.pt_section_name = value
            course.save(update_fields=['pt_section_name'])
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        if field_name == 'ao_section_name':
            course.ao_section_name = value
            course.save(update_fields=['ao_section_name'])
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        if field_name == 'exam_section_name':
            course.exam_section_name = value
            course.save(update_fields=['exam_section_name'])
            return JsonResponse({'success': True, 'field_name': field_name, 'value': value})

        # Handle score updates (specific to one student)
        enrollment = get_object_or_404(Enrollment, pk=enrollment_id, course=course)
        rec = enrollment.grade_record
        
        # Parse the value
        score_value = None
        if value:
            try:
                score_value = float(value)
            except ValueError:
                return JsonResponse({'success': False, 'error': 'Invalid number'}, status=400)
        
        # Determine which field to update
        if field_name.startswith('ww_'):
            # Written Work (CS) column
            col_num = int(field_name.split('_')[1]) - 1
            scores = list(rec.quiz_scores or [])
            # Extend list if needed
            while len(scores) <= col_num:
                scores.append(None)
            scores[col_num] = score_value
            # Trim trailing Nones
            while scores and scores[-1] is None:
                scores.pop()
            rec.quiz_scores = scores
            
        elif field_name.startswith('pt_'):
            # Performance Task column
            col_num = int(field_name.split('_')[1]) - 1
            scores = list(rec.performance_task_scores or [])
            # Extend list if needed
            while len(scores) <= col_num:
                scores.append(None)
            scores[col_num] = score_value
            # Trim trailing Nones
            while scores and scores[-1] is None:
                scores.pop()
            rec.performance_task_scores = scores

        elif field_name.startswith('ao_'):
            # Activity Output column
            col_num = int(field_name.split('_')[1]) - 1
            scores = list(rec.activity_scores or [])
            # Extend list if needed
            while len(scores) <= col_num:
                scores.append(None)
            scores[col_num] = score_value
            # Trim trailing Nones
            while scores and scores[-1] is None:
                scores.pop()
            rec.activity_scores = scores

        elif field_name == 'qa':
            # Major Exams
            rec.requirement_score = score_value

        else:
            return JsonResponse({'success': False, 'error': 'Unknown field'}, status=400)
        
        rec.save()
        
        return JsonResponse({
            'success': True,
            'message': 'Score saved',
            'enrollment_id': enrollment_id,
            'field_name': field_name,
            'value': score_value
        })
        
    except Exception as e:
        logger.error(f"Auto-save error: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@_instructor_required
def export_grades_txt(request, course_pk):
    course      = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    enrollments = (Enrollment.objects
                   .filter(course=course)
                   .select_related('student', 'grade_record')
                   .order_by('student__last_name', 'student__first_name'))
    lines = [
        f"GRADE SHEET — {course.code}: {course.title}",
        f"Semester: {course.get_semester_display()} S.Y. {course.school_year}",
        f"Instructor: {course.instructor.get_full_name()}",
        "=" * 70,
        f"{'No.':<4} {'Student Name':<30} {'CS(20%)':<10} "
        f"{'Req(40%)':<10} {'Exam(40%)':<10} {'Final':<8} {'Equiv':<8} {'Remarks'}",
        "-" * 70,
    ]
    for i, e in enumerate(enrollments, 1):
        rec  = getattr(e, 'grade_record', None)
        name = e.student.get_full_name()
        cs   = f"{rec.class_standing:.1f}"   if rec and rec.class_standing   is not None else '—'
        req  = f"{rec.requirement_score:.1f}" if rec and rec.requirement_score is not None else '—'
        exam = f"{rec.examination_average:.1f}" if rec and rec.examination_average is not None else '—'
        fg   = f"{rec.final_grade:.2f}"       if rec and rec.final_grade       is not None else '—'
        eq   = rec.equivalent_grade if rec else '—'
        rmk  = rec.remarks if rec else ''
        lines.append(
            f"{i:<4} {name:<30} {cs:<10} {req:<10} {exam:<10} {fg:<8} {eq:<8} {rmk}"
        )

    lines += ["", f"Passed: {sum(1 for e in enrollments if getattr(e,'grade_record',None) and e.grade_record.passed)}  "
                  f"Failed: {sum(1 for e in enrollments if getattr(e,'grade_record',None) and e.grade_record.final_grade is not None and not e.grade_record.passed)}"]

    response = HttpResponse('\n'.join(lines), content_type='text/plain')
    response['Content-Disposition'] = (
        f'attachment; filename="{course.code}_grades.txt"'
    )
    return response


# ─── Student: Grade Portal ────────────────────────────────────────────────────

@login_required
def student_grades(request):
    if not request.user.is_student:
        return redirect('accounts:instructor_dashboard')
    enrollments = (Enrollment.objects
                   .filter(student=request.user)
                   .select_related('course', 'course__instructor', 'grade_record'))
    grade_data = []
    for e in enrollments:
        rec = getattr(e, 'grade_record', None)
        grade_data.append({
            'enrollment': e,
            'course':     e.course,
            'record':     rec,
        })
    return render(request, 'grading/student_grades.html',
                  {'grade_data': grade_data})


@login_required
def student_course_grades(request, course_pk):
    """Detailed grade breakdown for one course — student view."""
    from attendance.models import AttendanceRecord

    enrollment = get_object_or_404(
        Enrollment, course_id=course_pk, student=request.user
    )
    course = enrollment.course
    rec = getattr(enrollment, 'grade_record', None)

    def _build_score_items(scores, names, max_scores, prefix):
        items = []
        if not scores:
            return items
        for i, s in enumerate(scores):
            name = (names[i] if names and i < len(names) else f'{prefix} {i+1}')
            mx   = (max_scores[i] if max_scores and i < len(max_scores) and max_scores[i] else 10)
            pct  = round(s / mx * 100, 1) if s is not None and mx else None
            items.append({'name': name, 'score': s, 'max': mx, 'pct': pct})
        return items

    cs_items  = []
    pt_items  = []
    ao_items  = []
    fcs_items = []
    fpt_items = []
    fao_items = []

    if rec:
        cs_items  = _build_score_items(rec.quiz_scores, rec.quiz_column_names,
                                        course.quiz_max_scores, 'CS')
        pt_items  = _build_score_items(rec.performance_task_scores, rec.pt_column_names,
                                        course.pt_max_scores, 'PT')
        ao_items  = _build_score_items(rec.activity_scores, rec.activity_column_names,
                                        course.activity_max_scores, 'AO')
        fcs_items = _build_score_items(rec.final_cs_scores, rec.final_cs_column_names,
                                        course.final_cs_max_scores, 'CS')
        fpt_items = _build_score_items(rec.final_pt_scores, rec.final_pt_column_names,
                                        course.final_pt_max_scores, 'PT')
        fao_items = _build_score_items(rec.final_activity_scores, rec.final_activity_column_names,
                                        course.final_activity_max_scores, 'AO')

    # Attendance summary
    att_qs    = AttendanceRecord.objects.filter(enrollment=enrollment)
    att_total = att_qs.count()
    att_summary = {
        'total':   att_total,
        'present': att_qs.filter(status='present').count(),
        'late':    att_qs.filter(status='late').count(),
        'absent':  att_qs.filter(status='absent').count(),
        'excused': att_qs.filter(status='excused').count(),
    }

    # Grade descriptor (NEMSU scale)
    def _descriptor(eq):
        try:
            gp = float(eq.split()[0])
        except (ValueError, AttributeError):
            return ''
        if gp == 1.0:  return 'Excellent'
        if gp <= 1.25: return 'Very Good'
        if gp <= 1.5:  return 'Good'
        if gp <= 1.75: return 'Very Satisfactory'
        if gp <= 2.0:  return 'Satisfactory'
        if gp <= 2.25: return 'Fairly Satisfactory'
        if gp <= 2.5:  return 'Fair'
        if gp <= 2.75: return 'Passing'
        if gp <= 3.0:  return 'Passed'
        return 'Failed'

    eq = rec.equivalent_grade if rec else '—'
    grade_summary = {
        'midterm':    rec.midterm_term_grade    if rec else None,
        'final_term': rec.final_term_grade      if rec else None,
        'final':      rec.final_semestral_grade if rec else None,
        'equiv':      eq,
        'descriptor': _descriptor(eq) if eq != '—' else '',
        'passed':     rec.passed if rec else None,
    }
    # Fall back to the legacy final_grade if semestral is unavailable
    if rec and grade_summary['final'] is None:
        grade_summary['final'] = rec.final_grade

    return render(request, 'grading/student_course_grades.html', {
        'enrollment':    enrollment,
        'course':        course,
        'record':        rec,
        'cs_items':      cs_items,
        'pt_items':      pt_items,
        'ao_items':      ao_items,
        'fcs_items':     fcs_items,
        'fpt_items':     fpt_items,
        'fao_items':     fao_items,
        'grade_summary': grade_summary,
        'att_summary':   att_summary,
    })


# ─── Grade Management (Settings) ─────────────────────────────────────────────

@_instructor_required
def grade_management(request, course_pk):
    """
    Dedicated grade management page: configure grading weights, section names,
    HPS (highest possible scores), and the grading rubric for a course.
    Changes apply to both Midterm and Final e-class record computations.
    """
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)

    errors = []

    if request.method == 'POST':
        action = request.POST.get('action', 'weights')

        if action == 'weights':
            # ── Grading weights ──────────────────────────────────────────────
            def _int(key, default):
                try:
                    v = int(request.POST.get(key, default))
                    return max(0, min(100, v))
                except (ValueError, TypeError):
                    return default

            cs_w   = _int('cs_weight',   20)
            pt_w   = _int('req_weight',  20)
            ao_w   = _int('ao_weight',   20)
            exam_w = _int('exam_weight', 40)

            if cs_w + pt_w + ao_w + exam_w != 100:
                errors.append('Weights must add up to exactly 100%.')
            else:
                course.cs_weight   = cs_w
                course.req_weight  = pt_w
                course.ao_weight   = ao_w
                course.exam_weight = exam_w

                # Section names
                course.cs_section_name   = request.POST.get('cs_section_name',   '').strip()[:100]
                course.pt_section_name   = request.POST.get('pt_section_name',   '').strip()[:100]
                course.ao_section_name   = request.POST.get('ao_section_name',   '').strip()[:100]
                course.exam_section_name = request.POST.get('exam_section_name', '').strip()[:100]

                course.save(update_fields=[
                    'cs_weight', 'req_weight', 'ao_weight', 'exam_weight',
                    'cs_section_name', 'pt_section_name',
                    'ao_section_name', 'exam_section_name',
                ])
                _log(request, 'grade_settings', target=course.code,
                     detail='Grading weights updated')
                messages.success(request, 'Grading weights and section names saved.')
                return redirect('grading:grade_management', course_pk=course_pk)

        elif action == 'hps':
            # ── Highest Possible Scores ──────────────────────────────────────
            def _pos(key, default=10):
                try:
                    v = int(request.POST.get(key, default))
                    return v if v > 0 else default
                except (ValueError, TypeError):
                    return default

            # Midterm HPS
            course.requirement_max = _pos('requirement_max', 100)

            # Final HPS
            course.final_exam_max = _pos('final_exam_max', 100)

            course.save(update_fields=['requirement_max', 'final_exam_max'])
            _log(request, 'grade_settings', target=course.code,
                 detail='HPS values updated')
            messages.success(request, 'Highest possible scores saved.')
            return redirect('grading:grade_management', course_pk=course_pk)

        elif action == 'rubric':
            # ── Grading rubric / description ─────────────────────────────────
            course.grading_system = request.POST.get('grading_system', '').strip()
            course.save(update_fields=['grading_system'])
            _log(request, 'grade_settings', target=course.code,
                 detail='Grading rubric updated')
            messages.success(request, 'Grading rubric saved.')
            return redirect('grading:grade_management', course_pk=course_pk)

    context = {
        'course': course,
        'errors': errors,
        # Transmutation table rows for display
        'transmutation_table': [
            (97, 100, '1.00'), (94, 96, '1.25'), (91, 93, '1.50'),
            (88, 90, '1.75'), (85, 87, '2.00'), (82, 84, '2.25'),
            (79, 81, '2.50'), (76, 78, '2.75'), (75, 75, '3.00'),
            (0,  74, '5.00'),
        ],
    }
    return render(request, 'grading/grade_management.html', context)
