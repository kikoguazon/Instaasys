import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from accounts.models import Course
from .models import Question
from .forms import QuestionGenerateForm, QuestionEditForm

logger = logging.getLogger(__name__)


def _instructor_required(view_func):
    from functools import wraps
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_instructor:
            messages.error(request, 'Instructor access required.')
            return redirect('accounts:login')
        return view_func(request, *args, **kwargs)
    return wrapper





# ─── Question Bank ────────────────────────────────────────────────────────────

from .models import Question, QuestionSet


# ─── Question Sets (Generation Tracking) ──────────────────────────────────────

@_instructor_required
def questionset_list(request, course_pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    question_sets_qs = course.question_sets.all()
    # Check if there are orphan questions (from before this update)
    if course.questions.filter(question_set__isnull=True).exists():
        legacy_qs, created = QuestionSet.objects.get_or_create(
            course=course,
            title="Legacy Assessment Set",
            defaults={'status': QuestionSet.STATUS_READY}
        )
        course.questions.filter(question_set__isnull=True).update(question_set=legacy_qs)

    debug_info = request.session.pop('debug_info', None)

    q = request.GET.get('q', '').strip()
    if q:
        question_sets_qs = question_sets_qs.filter(title__icontains=q)

    total_count = question_sets_qs.count()
    paginator = Paginator(question_sets_qs, 15)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    # JSON branch for infinite scroll
    if request.GET.get('format') == 'json':
        from django.template.loader import render_to_string
        html = render_to_string(
            'assessments/partials/questionset_rows.html',
            {'question_sets': page_obj, 'course': course, 'request': request},
        )
        return JsonResponse({
            'html': html,
            'has_next': page_obj.has_next(),
            'next_page': page_obj.next_page_number() if page_obj.has_next() else None,
            'total': total_count,
        })

    params = request.GET.copy()
    params.pop('page', None)

    context = {
        'course': course,
        'question_sets': page_obj,
        'page_obj': page_obj,
        'page_query': params.urlencode(),
        'debug_info': debug_info,
        'search': q,
    }
    return render(request, 'assessments/questionset_list.html', context)


@_instructor_required
def question_generate(request, course_pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    
    weekly_plan = course.weekly_plan or []
    has_syllabus = bool(weekly_plan)

    # Build syllabus_weeks for the template
    syllabus_weeks = []
    for item in weekly_plan:
        wn = item.get('week')
        if wn is None:
            continue
        
        raw_topics = item.get('topics', '')
        if isinstance(raw_topics, list):
            topic_str = ', '.join(str(t) for t in raw_topics)
        else:
            topic_str = str(raw_topics)
            
        syllabus_weeks.append({
            'week_number': wn,
            'topic': topic_str,
        })

    base_ctx = {
        'course': course,
        'syllabus_weeks': syllabus_weeks,
        'has_syllabus': has_syllabus,
        'qtype_choices': Question.TYPE_CHOICES,
        'bloom_choices': Question.BLOOM_CHOICES,
        'difficulty_choices': Question.DIFFICULTY_CHOICES,
    }

    if request.method == 'POST':
        form = QuestionGenerateForm(request.POST, weekly_plan=weekly_plan)
        logger.info(f"Question generation POST request received. POST data: {dict(request.POST)}")

        if form.is_valid():
            selected_weeks = form.cleaned_data['weeks']
            custom_topic   = form.cleaned_data.get('custom_topic', '').strip()
            assessment_type = form.cleaned_data.get('assessment_type', 'quiz')

            q_types = request.POST.getlist('question_types')
            logger.info(f"Form is valid. Selected weeks: {selected_weeks}, q_types: {q_types}, assessment_type: {assessment_type}")

            if not selected_weeks:
                messages.error(request, 'Please select at least one week.')
                return render(request, 'assessments/question_generate.html',
                              {**base_ctx, 'form': form})

            if not q_types:
                messages.error(request, 'Please select at least one question type.')
                return render(request, 'assessments/question_generate.html',
                              {**base_ctx, 'form': form})

            # ── Combine all selected weeks into a single assessment ──────────
            week_refs   = []   # ['Week 1', 'Week 3', ...]
            week_topics = []   # ['Intro to X', 'Advanced Y', ...]
            week_numbers = []
            for raw_week_topic in selected_weeks:
                if '|' in raw_week_topic:
                    wref, tstr = raw_week_topic.split('|', 1)
                else:
                    wref, tstr = '', raw_week_topic
                if wref.strip():
                    week_refs.append(wref.strip())
                if tstr.strip():
                    week_topics.append(tstr.strip())
                try:
                    week_numbers.append(int(wref.replace('Week', '').strip()))
                except ValueError:
                    pass

            # Pull content from syllabus weekly plan directly
            syllabus_texts = []
            for item in weekly_plan:
                if item.get('week') in week_numbers:
                    raw_topics = item.get('topics', '')
                    topic_str = ', '.join(str(t) for t in raw_topics) if isinstance(raw_topics, list) else str(raw_topics)
                    cilos = item.get('cilos', '')
                    methodology = item.get('methodology', '')
                    assessment = item.get('assessment', '')
                    resources = item.get('resources', '')
                    
                    parts = filter(None, [
                        f"Topics: {topic_str}" if topic_str else "",
                        f"Learning Outcomes: {cilos}" if cilos else "",
                        f"Methodology: {methodology}" if methodology else "",
                        f"Assessment: {assessment}" if assessment else "",
                        f"Resources: {resources}" if resources else "",
                    ])
                    text = f"Week {item.get('week')}:\n" + "\n".join(parts)
                    syllabus_texts.append(text)
                    
            presentation_content = '\n\n'.join(syllabus_texts)[:3500]

            # Build a combined topic and week label
            combined_topic = custom_topic or ', '.join(week_topics) or 'Custom'
            if len(week_refs) == 1:
                combined_week_ref = week_refs[0]
            elif week_refs:
                week_numbers = []
                for w in week_refs:
                    num = w.replace('Week', '').strip()
                    try:
                        week_numbers.append(int(num))
                    except ValueError:
                        pass

                # Format as range (3–8) if consecutive, else list (3 and 8)
                if len(week_numbers) == 2 and week_numbers[1] - week_numbers[0] == 1:
                    combined_week_ref = f"Weeks {week_numbers[0]}–{week_numbers[1]}"
                elif len(week_numbers) == 2:
                    combined_week_ref = f"Weeks {week_numbers[0]} and {week_numbers[1]}"
                else:
                    combined_week_ref = 'Weeks ' + ', '.join(str(n) for n in week_numbers)
            else:
                combined_week_ref = ''

            title = f"Assessment: {combined_week_ref or 'Custom'}"

            # Resolve per-type counts + bloom + difficulty up front; skip zero/invalid ones
            valid_blooms = {c[0] for c in Question.BLOOM_CHOICES}
            valid_diffs  = {c[0] for c in Question.DIFFICULTY_CHOICES}
            config_by_type = {}  # q_type -> {'count': int, 'bloom': str, 'difficulty': str}
            for q_type in q_types:
                count_str = request.POST.get(f'{q_type}_count', '0')
                try:
                    count = int(count_str)
                except ValueError:
                    logger.warning(f"Invalid count for {q_type}: '{count_str}'")
                    continue
                if count <= 0:
                    continue
                bloom = request.POST.get(f'{q_type}_bloom', 'remember')
                if bloom not in valid_blooms:
                    bloom = 'remember'
                diff = request.POST.get(f'{q_type}_difficulty', 'average')
                if diff not in valid_diffs:
                    diff = 'average'
                config_by_type[q_type] = {'count': count, 'bloom': bloom, 'difficulty': diff}

            if not config_by_type:
                messages.error(request, 'Please set at least one question type to a count greater than zero.')
                return render(request, 'assessments/question_generate.html',
                              {**base_ctx, 'form': form})

            # Create ONE QuestionSet for the whole generation
            qs = QuestionSet.objects.create(
                course=course,
                title=title,
                status=QuestionSet.STATUS_PENDING,
            )
            logger.info(f"Creating combined question set {qs.pk} for {list(config_by_type.keys())} over {combined_week_ref or 'Custom'}")

            # Queue one task per q_type, all writing into the same QuestionSet
            for q_type, cfg in config_by_type.items():
                count       = cfg['count']
                type_bloom  = cfg['bloom']
                type_diff   = cfg['difficulty']
                try:
                    from .tasks import generate_questions_task
                    generate_questions_task.delay(
                        questionset_id=qs.pk,
                        topic=combined_topic,
                        bloom_level=type_bloom,
                        q_type=q_type,
                        count=count,
                        difficulty=type_diff,
                        week_ref=combined_week_ref,
                        presentation_content=presentation_content,
                        assessment_type=assessment_type,
                    )
                except Exception as exc:
                    logger.warning(f"Celery/Redis unavailable, falling back to sync: {exc}")
                    messages.info(request, f'Queue unavailable – generating {q_type.replace("_"," ")} now. This may take a few seconds.')
                    try:
                        _generate_questions_sync(
                            qs, combined_topic, type_bloom, q_type,
                            count, type_diff, combined_week_ref,
                            presentation_content=presentation_content,
                            assessment_type=assessment_type,
                        )
                    except RuntimeError as e:
                        logger.exception("Sync question generation failed")
                        qs.status = QuestionSet.STATUS_FAILED
                        qs.error_msg = str(e)
                        qs.save()
                        messages.error(request, f'Failed to generate {q_type.replace("_"," ")} questions: {e}')
                        request.session['debug_info'] = {
                            'error_message': str(e),
                            'system_prompt': getattr(e, 'system_prompt', ''),
                            'user_prompt': getattr(e, 'user_prompt', ''),
                            'raw_ai_response': getattr(e, 'raw_ai_response', ''),
                        }

            messages.success(request, f'Queued generation for "{title}" ({len(config_by_type)} question type{"s" if len(config_by_type)!=1 else ""}).')

            return redirect('assessments:questionset_list', course_pk=course_pk)
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Form Error ({field}): {error}")
    else:
        form = QuestionGenerateForm(weekly_plan=weekly_plan)

    debug_info = request.session.pop('debug_info', None)
    return render(request, 'assessments/question_generate.html',
                  {**base_ctx, 'form': form, 'debug_info': debug_info})


def _generate_questions_sync(questionset, topic, bloom_level, q_type, count, difficulty, week_ref,
                              presentation_content: str = '', assessment_type: str = 'quiz'):
    from instaasys.ai_service import generate_questions
    valid_bloom = {c[0] for c in Question.BLOOM_CHOICES}
    valid_diff = {c[0] for c in Question.DIFFICULTY_CHOICES}
    
    logger.info(f"Starting sync question generation: questionset={questionset.pk}, topic='{topic}', bloom_level='{bloom_level}', q_type='{q_type}', count={count}, difficulty='{difficulty}', week_ref='{week_ref}', assessment_type='{assessment_type}'")
    
    try:
        questions_data = generate_questions(
            topic=topic,
            bloom_level=bloom_level,
            q_type=q_type,
            count=count,
            course_title=questionset.course.title,
            difficulty=difficulty,
            presentation_content=presentation_content,
            assessment_type=assessment_type,
        )
        logger.info(f"Generated {len(questions_data)} questions from AI service")
        
        created_count = 0
        for q in questions_data:
            q_bloom = q.get('bloom_level', bloom_level)
            if q_bloom not in valid_bloom:
                q_bloom = bloom_level
            q_diff = q.get('difficulty', difficulty)
            if q_diff not in valid_diff:
                q_diff = difficulty

            Question.objects.create(
                course          = questionset.course,
                question_set    = questionset,
                topic           = topic,
                week_ref        = week_ref,
                question_type   = q_type,
                bloom_level     = q_bloom,
                difficulty      = q_diff,
                content         = q.get('content', ''),
                choices         = q.get('choices'),
                answer_key      = q.get('answer_key', ''),
                explanation     = q.get('explanation', ''),
                rubric          = q.get('rubric', ''),
                expected_answer = q.get('expected_answer', ''),
                follow_up       = q.get('follow_up', ''),
            )
            created_count += 1
            
        logger.info(f"Successfully created {created_count} questions in database")
        questionset.status = QuestionSet.STATUS_READY
        questionset.save()
        
    except Exception as e:
        logger.exception(f"Sync question generation failed: {e}")
        questionset.status = QuestionSet.STATUS_FAILED
        questionset.error_msg = str(e)
        questionset.save()
        raise


@login_required
def questionset_status_api(request, pk):
    qs = get_object_or_404(QuestionSet, pk=pk, course__instructor=request.user)
    return JsonResponse({
        'status': qs.status,
        'error_msg': qs.error_msg,
    })


@_instructor_required
def questionset_delete(request, course_pk, pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    qs = get_object_or_404(QuestionSet, pk=pk, course=course)
    if request.method == 'POST':
        qs.delete()
        messages.success(request, 'Question set deleted.')
        return redirect('assessments:questionset_list', course_pk=course_pk)
    return render(request, 'assessments/questionset_confirm_delete.html',
                  {'course': course, 'questionset': qs})


@_instructor_required
def questionset_detail(request, course_pk, pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    qs = get_object_or_404(QuestionSet, pk=pk, course=course)
    questions = qs.questions.all()

    q_type  = request.GET.get('type', '')
    bloom   = request.GET.get('bloom', '')
    if q_type:  questions = questions.filter(question_type=q_type)
    if bloom:   questions = questions.filter(bloom_level=bloom)

    topics_summary = {}
    for q in qs.questions.all():
        key = q.week_ref or q.topic
        if key not in topics_summary:
            topics_summary[key] = {'total': 0, 'mc': 0, 'tf': 0, 'id': 0, 'essay': 0, 'oral': 0}
        topics_summary[key]['total'] += 1
        type_map = {'multiple_choice': 'mc', 'true_false': 'tf', 'identification': 'id', 'essay': 'essay', 'oral': 'oral'}
        short = type_map.get(q.question_type, 'essay')
        topics_summary[key][short] += 1

    context = {
        'course': course,
        'questionset': qs,
        'questions': questions,
        'topics_summary': topics_summary,
        'filter_type': q_type,
        'filter_bloom': bloom,
        'type_choices': Question.TYPE_CHOICES,
        'bloom_choices': Question.BLOOM_CHOICES,
    }
    return render(request, 'assessments/questionset_detail.html', context)


# ─── Individual Question Logic ────────────────────────────────────────────────

@_instructor_required
def question_detail(request, course_pk, pk):
    course   = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    question = get_object_or_404(Question, pk=pk, course=course)
    return render(request, 'assessments/question_detail.html',
                  {'course': course, 'question': question})


@_instructor_required
def question_edit(request, course_pk, pk):
    course   = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    question = get_object_or_404(Question, pk=pk, course=course)
    if request.method == 'POST':
        form = QuestionEditForm(request.POST, instance=question)
        if form.is_valid():
            form.save()
            messages.success(request, 'Question updated.')
            return redirect('assessments:question_detail', course_pk=course_pk, pk=pk)
    else:
        form = QuestionEditForm(instance=question)
    return render(request, 'assessments/question_edit.html',
                  {'form': form, 'course': course, 'question': question})


@_instructor_required
def question_delete(request, course_pk, pk):
    course   = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    question = get_object_or_404(Question, pk=pk, course=course)
    if request.method == 'POST':
        qs_id = question.question_set_id
        question.delete()
        messages.success(request, 'Question deleted.')
        if qs_id:
            return redirect('assessments:questionset_detail', course_pk=course_pk, pk=qs_id)
        return redirect('assessments:questionset_list', course_pk=course_pk)
    return render(request, 'assessments/question_confirm_delete.html',
                  {'course': course, 'question': question})


@_instructor_required
def questionset_export(request, course_pk, pk):
    """Export all questions for a specific QuestionSet as plain text."""
    course    = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    qs = get_object_or_404(QuestionSet, pk=pk, course=course)
    questions = qs.questions.all()

    q_type  = request.GET.get('type', '')
    bloom   = request.GET.get('bloom', '')
    if q_type:  questions = questions.filter(question_type=q_type)
    if bloom:   questions = questions.filter(bloom_level=bloom)

    lines = [
        f"ASSESSMENT — {course.code}: {course.title}",
        f"Topic: {qs.title}",
        f"Total: {questions.count()} questions",
        "=" * 60, ""
    ]
    for i, q in enumerate(questions, 1):
        lines.append(f"{i}. [{q.get_bloom_level_display()} | "
                     f"{q.get_question_type_display()} | "
                     f"{q.get_difficulty_display()}]")
        lines.append(f"   {q.content}")
        if q.choices:
            for letter, text in q.choices.items():
                lines.append(f"   {letter}. {text}")
            lines.append(f"   Answer: {q.answer_key}")
        if q.explanation:
            lines.append(f"   Explanation: {q.explanation}")
        if q.rubric:
            lines.append(f"   Rubric: {q.rubric}")
        if q.expected_answer:
            lines.append(f"   Expected: {q.expected_answer}")
        if q.follow_up:
            lines.append(f"   Follow-up: {q.follow_up}")
        lines.append("")

    content = "\n".join(lines)
    response = HttpResponse(content, content_type='text/plain')
    safe_title = qs.title.replace(' ', '_').replace(':', '')[:30]
    response['Content-Disposition'] = f'attachment; filename="{course.code}_{safe_title}_questions.txt"'
    return response


@_instructor_required
def questionset_export_markdown(request, course_pk, pk):
    """Export QuestionSet as a Markdown document (grouped by question type)."""
    course    = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    qs        = get_object_or_404(QuestionSet, pk=pk, course=course)
    questions = list(qs.questions.all())

    include_answers = request.GET.get('answers', 'true').lower() == 'true'
    q_type = request.GET.get('type', '')
    bloom  = request.GET.get('bloom', '')
    if q_type:
        questions = [q for q in questions if q.question_type == q_type]
    if bloom:
        questions = [q for q in questions if q.bloom_level == bloom]

    groups = {
        'multiple_choice': [q for q in questions if q.question_type == 'multiple_choice'],
        'true_false':      [q for q in questions if q.question_type == 'true_false'],
        'identification':  [q for q in questions if q.question_type == 'identification'],
        'essay':           [q for q in questions if q.question_type == 'essay'],
        'oral':            [q for q in questions if q.question_type == 'oral'],
    }
    section_titles = {
        'multiple_choice': 'Multiple Choice',
        'true_false':      'True or False',
        'identification':  'Identification',
        'essay':           'Essay',
        'oral':            'Oral Assessment',
    }

    lines = [
        f"# {course.code} — {qs.title}",
        "",
        f"**Course:** {course.title}  ",
        f"**Total questions:** {len(questions)}",
        "",
    ]

    counter = 0
    for key in ('multiple_choice', 'true_false', 'identification', 'essay', 'oral'):
        items = groups[key]
        if not items:
            continue
        lines.append(f"## {section_titles[key]}")
        lines.append("")
        for q in items:
            counter += 1
            lines.append(f"**{counter}.** {q.content}")
            if key == 'multiple_choice' and q.choices:
                for letter, text in q.choices.items():
                    is_correct = include_answers and letter == q.answer_key
                    marker = "**" if is_correct else ""
                    lines.append(f"   - {marker}{letter}.{marker} {text}")
            if key == 'true_false' and include_answers:
                tf = "TRUE" if q.answer_key == 'A' else "FALSE"
                lines.append(f"   - *Answer:* **{tf}**")
            if key == 'identification' and include_answers and q.answer_key:
                lines.append(f"   - *Answer:* **{q.answer_key}**")
            if include_answers:
                if key == 'multiple_choice' and q.answer_key:
                    lines.append(f"   - *Answer:* **{q.answer_key}**")
                if q.explanation:
                    lines.append(f"   - *Explanation:* {q.explanation}")
                if q.expected_answer:
                    lines.append(f"   - *Expected:* {q.expected_answer}")
                if q.rubric:
                    lines.append(f"   - *Rubric:* {q.rubric}")
                if q.follow_up:
                    lines.append(f"   - *Follow-up:* {q.follow_up}")
            lines.append("")
        lines.append("")

    content = "\n".join(lines)
    response = HttpResponse(content, content_type='text/markdown; charset=utf-8')
    safe_title = qs.title.replace(' ', '_').replace(':', '')[:30]
    response['Content-Disposition'] = f'attachment; filename="{course.code}_{safe_title}_questions.md"'
    return response


@_instructor_required
def questionset_preview(request, course_pk, pk):
    """HTML preview that mirrors the DOCX layout so instructors can review
    the assessment before downloading."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    qs = get_object_or_404(QuestionSet, pk=pk, course=course)
    questions = list(qs.questions.all())

    include_answers = request.GET.get('answers', 'true').lower() == 'true'

    # Preview presentation toggles (stateless URL params)
    mode             = request.GET.get('mode', 'institutional')
    if mode not in ('institutional', 'minimalist'):
        mode = 'institutional'
    show_header      = request.GET.get('header', 'true').lower() != 'false'
    show_instructions= request.GET.get('instructions', 'true').lower() != 'false'
    theme            = request.GET.get('theme', 'light')
    if theme not in ('light', 'dark'):
        theme = 'light'
    # Minimalist mode implies no header + no directions unless caller overrides
    if mode == 'minimalist':
        if 'header' not in request.GET:
            show_header = False
        if 'instructions' not in request.GET:
            show_instructions = False

    q_type = request.GET.get('type', '')
    bloom = request.GET.get('bloom', '')
    if q_type:
        questions = [q for q in questions if q.question_type == q_type]
    if bloom:
        questions = [q for q in questions if q.bloom_level == bloom]

    # Group by type in the same order the DOCX uses
    groups = {
        'multiple_choice': [q for q in questions if q.question_type == 'multiple_choice'],
        'true_false':      [q for q in questions if q.question_type == 'true_false'],
        'identification':  [q for q in questions if q.question_type == 'identification'],
        'essay':           [q for q in questions if q.question_type == 'essay'],
        'oral':            [q for q in questions if q.question_type == 'oral'],
    }

    # Pair MC questions into 2-column rows to match the DOCX layout
    mc_rows = []
    mc = groups['multiple_choice']
    for i in range(0, len(mc), 2):
        mc_rows.append((
            (i + 1, mc[i]),
            (i + 2, mc[i + 1]) if i + 1 < len(mc) else None,
        ))

    # Build toolbar querystring variants — each link preserves current state
    # except the one parameter it is meant to change.
    def _build_qs(**overrides):
        params = {
            'answers':      'true' if include_answers else 'false',
            'mode':         mode,
            'theme':        theme,
            'header':       'true' if show_header else 'false',
            'instructions': 'true' if show_instructions else 'false',
        }
        if q_type:
            params['type'] = q_type
        if bloom:
            params['bloom'] = bloom
        params.update(overrides)
        return '?' + '&'.join(f'{k}={v}' for k, v in params.items())

    toolbar_links = {
        'answers_on':  _build_qs(answers='true'),
        'answers_off': _build_qs(answers='false'),
        'mode_inst':   _build_qs(mode='institutional'),
        'mode_mini':   _build_qs(mode='minimalist'),
        'theme_light': _build_qs(theme='light'),
        'theme_dark':  _build_qs(theme='dark'),
    }

    return render(request, 'assessments/questionset_preview.html', {
        'course': course,
        'questionset': qs,
        'groups': groups,
        'mc_rows': mc_rows,
        'has_any': any(groups.values()),
        'include_answers': include_answers,
        'filter_type': q_type,
        'filter_bloom': bloom,
        'mode': mode,
        'show_header': show_header,
        'show_instructions': show_instructions,
        'theme': theme,
        'toolbar_links': toolbar_links,
    })


@_instructor_required
def questionset_export_docx(request, course_pk, pk):
    """Export QuestionSet as DOCX with institutional format."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    qs = get_object_or_404(QuestionSet, pk=pk, course=course)
    questions = list(qs.questions.all())
    
    # Check if answer key should be included
    include_answers = request.GET.get('answers', 'true').lower() == 'true'
    
    # Apply filters if provided
    q_type = request.GET.get('type', '')
    bloom = request.GET.get('bloom', '')
    if q_type:
        questions = [q for q in questions if q.question_type == q_type]
    if bloom:
        questions = [q for q in questions if q.bloom_level == bloom]
    
    # Generate DOCX
    from .assessment_builder import build_assessment_docx
    docx_bytes = build_assessment_docx(qs, questions, course, include_answers)
    
    # Return as download
    response = HttpResponse(
        docx_bytes,
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    )
    safe_title = qs.title.replace(' ', '_').replace(':', '')[:30]
    filename = f"{course.code}_{safe_title}_exam.docx"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


# ─── Inline edit + single-question regenerate (preview toolbar actions) ──────

INLINE_EDITABLE_FIELDS = {'content', 'answer_key'}
# Choice fields are addressed as `choice_<LETTER>` (e.g. choice_A) and write
# into the `choices` JSON dict on the question.
CHOICE_FIELD_PREFIX = 'choice_'


@_instructor_required
def question_inline_update(request, course_pk, pk):
    """Update a single field on a question. Accepts `content`, `answer_key`,
    and `choice_<LETTER>` (writes into the `choices` JSON dict). Any other
    field is rejected."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)

    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    question = get_object_or_404(Question, pk=pk, course=course)

    field = (request.POST.get('field') or '').strip()
    value = request.POST.get('value', '')

    is_choice = field.startswith(CHOICE_FIELD_PREFIX)
    if not is_choice and field not in INLINE_EDITABLE_FIELDS:
        return JsonResponse({'ok': False, 'error': f'Field "{field}" not editable inline.'}, status=400)

    value = value.strip()
    if is_choice:
        letter = field[len(CHOICE_FIELD_PREFIX):]
        if not (len(letter) == 1 and letter.isalpha()):
            return JsonResponse({'ok': False, 'error': 'Invalid choice letter.'}, status=400)
        letter = letter.upper()
        if len(value) > 2000:
            return JsonResponse({'ok': False, 'error': 'Choice too long.'}, status=400)
        choices = dict(question.choices or {})
        if letter not in choices:
            return JsonResponse({'ok': False, 'error': f'Choice "{letter}" not on this question.'}, status=400)
        choices[letter] = value
        question.choices = choices
        question.save(update_fields=['choices'])
        logger.info(f"Inline-updated question {question.pk} choice={letter}")
        return JsonResponse({'ok': True, 'value': value})

    if field == 'answer_key':
        # MC stores letter; TF stores 'A' (TRUE) or 'B' (FALSE); keep short
        if len(value) > 500:
            return JsonResponse({'ok': False, 'error': 'Answer too long.'}, status=400)
    else:
        if len(value) > 5000:
            return JsonResponse({'ok': False, 'error': 'Content too long.'}, status=400)

    setattr(question, field, value)
    question.save(update_fields=[field])
    logger.info(f"Inline-updated question {question.pk} field={field}")
    return JsonResponse({'ok': True, 'value': value})


@_instructor_required
def question_regenerate_item(request, course_pk, pk):
    """Regenerate a single question via AI using its existing topic/type/bloom/
    difficulty/week_ref. Replaces the question's content/choices/answer_key/
    explanation in place — preserves the row id so the UI can swap content
    without reordering."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)

    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    question = get_object_or_404(Question, pk=pk, course=course)

    # Re-derive presentation grounding from the original week reference if we
    # can — keeps the regenerated question aligned with the same syllabus content.
    presentation_content = ''
    try:
        import re
        week_numbers = [int(n) for n in re.findall(r'\d+', question.week_ref or '')]
        if week_numbers and course.weekly_plan:
            syllabus_texts = []
            for item in course.weekly_plan:
                if item.get('week') in week_numbers:
                    raw_topics = item.get('topics', '')
                    topic_str = ', '.join(str(t) for t in raw_topics) if isinstance(raw_topics, list) else str(raw_topics)
                    cilos = item.get('cilos', '')
                    methodology = item.get('methodology', '')
                    assessment = item.get('assessment', '')
                    resources = item.get('resources', '')
                    
                    parts = filter(None, [
                        f"Topics: {topic_str}" if topic_str else "",
                        f"Learning Outcomes: {cilos}" if cilos else "",
                        f"Methodology: {methodology}" if methodology else "",
                        f"Assessment: {assessment}" if assessment else "",
                        f"Resources: {resources}" if resources else "",
                    ])
                    text = f"Week {item.get('week')}:\n" + "\n".join(parts)
                    syllabus_texts.append(text)
            presentation_content = '\n\n'.join(syllabus_texts)[:3500]
    except Exception as exc:
        logger.warning(f"Could not re-derive presentation content for regen: {exc}")

    try:
        from instaasys.ai_service import generate_questions
        results = generate_questions(
            topic=question.topic,
            bloom_level=question.bloom_level,
            q_type=question.question_type,
            count=1,
            course_title=course.title,
            difficulty=question.difficulty,
            presentation_content=presentation_content,
        )
    except Exception as exc:
        logger.exception("Single-question regeneration failed")
        return JsonResponse({'ok': False, 'error': str(exc)}, status=500)

    if not results:
        return JsonResponse({'ok': False, 'error': 'AI returned no question.'}, status=502)

    new_q = results[0]
    question.content       = new_q.get('content', question.content)
    question.choices       = new_q.get('choices', question.choices)
    question.answer_key    = new_q.get('answer_key', question.answer_key)
    question.explanation   = new_q.get('explanation', question.explanation)
    question.rubric        = new_q.get('rubric', question.rubric)
    question.expected_answer = new_q.get('expected_answer', question.expected_answer)
    question.follow_up     = new_q.get('follow_up', question.follow_up)
    question.save()
    logger.info(f"Regenerated question {question.pk} (type={question.question_type})")

    return JsonResponse({
        'ok': True,
        'question': {
            'id':          question.pk,
            'content':     question.content,
            'choices':     question.choices,
            'answer_key':  question.answer_key,
            'explanation': question.explanation,
            'rubric':      question.rubric,
            'expected_answer': question.expected_answer,
            'follow_up':   question.follow_up,
        },
    })