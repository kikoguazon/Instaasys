import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.core.files.base import ContentFile
from accounts.models import Course
from .models import TableOfSpecifications
from .forms import TOSForm


def _instructor_required(view_func):
    """Decorator: must be logged in + instructor role."""
    from functools import wraps
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_instructor:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': 'Instructor access required.'}, status=403)

            messages.error(request, "Instructor access required.")
            return redirect('accounts:login')
        return view_func(request, *args, **kwargs)
    return wrapper


@_instructor_required
def tos_list(request, course_pk):
    course   = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    tos_list = course.tos_list.all()
    return render(request, 'tos/tos_list.html',
                  {'course': course, 'tos_list': tos_list})


@_instructor_required
def tos_create(request, course_pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)

    if request.method == 'POST':
        form = TOSForm(request.POST)
        if form.is_valid():
            topics_raw = request.POST.get('topics_json', '[]')
            try:
                topics = json.loads(topics_raw)
            except json.JSONDecodeError:
                topics = []

            if not topics:
                messages.error(request, "Please add at least one topic.")
                return render(request, 'tos/tos_form.html',
                              {'form': form, 'course': course})

            tos = TableOfSpecifications.objects.create(
                course=course,
                exam_type=form.cleaned_data['exam_type'],
                total_items=form.cleaned_data['total_items'],
                topics_data=topics,
                status='pending',
            )

            try:
                from .tasks import generate_tos_task
                generate_tos_task.delay(tos.id)
                messages.info(request,
                    "TOS is being generated. Refresh in ~20 seconds.")
            except Exception:
                _generate_tos_sync(tos)
                messages.success(request, "TOS generated successfully!")

            return redirect('tos:tos_detail', course_pk=course_pk, pk=tos.pk)
    else:
        form = TOSForm()

    return render(request, 'tos/tos_form.html',
                  {'form': form, 'course': course})


def _generate_tos_sync(tos):
    from instaasys.ai_service import generate_tos
    from .tos_builder import build_tos_xlsx
    try:
        ai_data = generate_tos(
            topics=tos.topics_data,
            total_items=tos.total_items,
            exam_type=tos.exam_type,
            course_title=tos.course.title,
        )
        tos.tos_data = ai_data
        xlsx_bytes   = build_tos_xlsx(ai_data)
        filename     = f"tos_{tos.exam_type.replace(' ', '_')}_{tos.id}.xlsx"
        tos.xlsx_file.save(filename, ContentFile(xlsx_bytes), save=False)
        tos.status = 'ready'
        tos.save()
    except Exception as exc:
        tos.status    = 'failed'
        tos.error_msg = str(exc)
        tos.save()
        raise


@_instructor_required
def tos_detail(request, course_pk, pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    tos    = get_object_or_404(TableOfSpecifications, pk=pk, course=course)
    return render(request, 'tos/tos_detail.html',
                  {'course': course, 'tos': tos})


@_instructor_required
def tos_download(request, course_pk, pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    tos    = get_object_or_404(TableOfSpecifications, pk=pk, course=course,
                                status='ready')
    if not tos.xlsx_file:
        messages.error(request, "File not ready yet.")
        return redirect('tos:tos_detail', course_pk=course_pk, pk=pk)

    response = HttpResponse(
        tos.xlsx_file.read(),
        content_type=(
            'application/vnd.openxmlformats-officedocument'
            '.spreadsheetml.sheet'
        )
    )
    filename = f"{course.code}_{tos.exam_type.replace(' ', '_')}_TOS.xlsx"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@login_required
def tos_status_api(request, pk):
    tos = get_object_or_404(TableOfSpecifications, pk=pk,
                              course__instructor=request.user)
    return JsonResponse({'status': tos.status, 'error': tos.error_msg})


@_instructor_required
def tos_delete(request, course_pk, pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    tos = get_object_or_404(TableOfSpecifications, pk=pk, course=course)
    if request.method == 'POST':
        tos.delete()
        messages.success(request, 'Table of Specifications deleted.')
        return redirect('tos:tos_list', course_pk=course_pk)
    return render(request, 'tos/tos_confirm_delete.html',
                  {'course': course, 'tos': tos})


@_instructor_required
def tos_syllabus_topics_api(request, course_pk):
    """
    Returns the course's weekly plan as a JSON list of topics with hours,
    so the TOS form can auto-populate the topics table from the syllabus.

    Each entry:
      { week, label, topic, hours, cilos }
    where `topic` is the joined topics string for that week and `hours` is
    derived from the course's credit hours (default 5 per week).
    """
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)

    weekly_plan = course.weekly_plan or []
    if not weekly_plan:
        return JsonResponse({'weeks': [], 'hours_per_week': 5})

    # Derive default hours per week from course.hours field
    # e.g. "2 hrs lec, 3 hrs lab" → 5
    hours_per_week = _parse_hours_per_week(course.hours)

    weeks = []
    for entry in weekly_plan:
        week_num = entry.get('week', '')
        label = entry.get('label', '')
        topics = entry.get('topics', [])
        cilos = entry.get('cilos', [])

        # Build a readable topic name: use label if it's an exam week,
        # otherwise join the topics list
        if label and not topics:
            topic_name = label
        elif topics:
            topic_name = topics[0] if len(topics) == 1 else '; '.join(topics)
        else:
            topic_name = f"Week {week_num}"

        weeks.append({
            'week': week_num,
            'label': label,
            'topic': topic_name,
            'topics_list': topics,
            'hours': hours_per_week,
            'cilos': cilos,
        })

    return JsonResponse({'weeks': weeks, 'hours_per_week': hours_per_week})


def _parse_hours_per_week(hours_str: str) -> int:
    """
    Parse a hours string like '2 hrs lec, 3 hrs lab' → 5.
    Falls back to 5 if parsing fails.
    """
    if not hours_str:
        return 5
    import re
    nums = re.findall(r'\d+', hours_str)
    total = sum(int(n) for n in nums)
    return total if total > 0 else 5
