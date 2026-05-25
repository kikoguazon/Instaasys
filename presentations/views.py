import copy
import json
import logging
import random
import concurrent.futures
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.core.files.base import ContentFile
from accounts.models import Course
from .models import LessonPlan
from .forms import LessonGenerateForm

logger = logging.getLogger(__name__)


def _sanitize_hex(val: str, fallback: str) -> str:
    if isinstance(val, str):
        v = val.strip().lstrip('#')
        if len(v) == 6:
            try:
                int(v, 16)
                return '#' + v.upper()
            except ValueError:
                pass
    return fallback


def _build_palette_css(palette: dict) -> str:
    """Convert an AI-generated hex palette dict to CSS custom property declarations."""
    def h(key, fallback):
        return _sanitize_hex(palette.get(key) or '', fallback)

    accents = palette.get('content_accents') or []

    def a(i, fallback):
        return _sanitize_hex(accents[i] if i < len(accents) else '', fallback)

    return (
        f"  --s-bg: {h('dark', '#0F172A')};\n"
        f"  --s-bg-light: {h('bg', '#F1F5F9')};\n"
        f"  --s-bg-card: {h('bg', '#F1F5F9')};\n"
        f"  --s-accent: {h('accent', '#3B82F6')};\n"
        f"  --s-accent-soft: {h('light', '#DBEAFE')};\n"
        f"  --s-accent-dark: {h('primary', '#1E40AF')};\n"
        f"  --s-text: {h('text_light', '#F8FAFC')};\n"
        f"  --s-text-dark: {h('text', '#1E293B')};\n"
        f"  --s-text-muted: {h('muted', '#94A3B8')};\n"
        f"  --s-border: {h('light', '#DBEAFE')};\n"
        f"  --s-gradient-start: {h('gradient_start', '#1E293B')};\n"
        f"  --s-gradient-end: {h('gradient_end', '#0F172A')};\n"
        f"  --s-obj-color: {h('primary', '#1E40AF')};\n"
        f"  --s-mid: {h('mid', '#1E293B')};\n"
        f"  --s-content-accent-1: {a(0, '#3B82F6')};\n"
        f"  --s-content-accent-2: {a(1, '#0D9488')};\n"
        f"  --s-content-accent-3: {a(2, '#4338CA')};\n"
        f"  --s-content-accent-4: {a(3, '#D97706')};\n"
        f"  --s-content-accent-5: {a(4, '#7C3AED')};\n"
        f"  --s-content-accent-6: {a(5, '#1E40AF')};\n"
    )


DESIGN_VARIANTS = (
    'minimalist', 'academic', 'modern', 'creative',
    'corporate',  'nature',   'tech',   'elegant',
)


LAYOUT_PATTERNS = (
    'alternating-split',     # R, L, R, L ... images flip sides each slide
    'hero-led',              # H, C, R, C ... image-bottom hero leads, occasional split
    'multi-block-grid',      # M, C, M, L ... topics presented as block cards
    'classic-bullets',       # C, C, R, C, L ... mostly bullets, occasional image
    'mosaic',                # R, M, L, H, C ... rotating layouts every slide
    'image-right-emphasis',  # R, R, C, H ... bias toward image-right
    'image-left-emphasis',   # L, L, C, H ... bias toward image-left
    'split-then-hero',       # R, L, H, C ... splits first then hero highlight
)

_PATTERN_SEQUENCES = {
    'alternating-split':     ['text_left_image_right', 'image_left_text_right'],
    'hero-led':              ['hero_image_bottom', 'content',
                              'text_left_image_right', 'content'],
    'multi-block-grid':      ['multi_block', 'content',
                              'multi_block', 'image_left_text_right'],
    'classic-bullets':       ['content', 'content', 'text_left_image_right',
                              'content', 'image_left_text_right'],
    'mosaic':                ['text_left_image_right', 'multi_block',
                              'image_left_text_right', 'hero_image_bottom', 'content'],
    'image-right-emphasis':  ['text_left_image_right', 'text_left_image_right',
                              'content', 'hero_image_bottom'],
    'image-left-emphasis':   ['image_left_text_right', 'image_left_text_right',
                              'content', 'hero_image_bottom'],
    'split-then-hero':       ['text_left_image_right', 'image_left_text_right',
                              'hero_image_bottom', 'content'],
}

_IMAGE_LAYOUT_NAMES = {'text_left_image_right', 'image_left_text_right', 'hero_image_bottom'}
_SPECIAL_LAYOUTS = {'title', 'objectives', 'section', 'divider', 'summary', 'conclusion'}
_SPECIAL_TITLE_KEYWORDS = ('objective', 'summary', 'recap', 'takeaway', 'conclusion')


def _pick_unique(plan, key, choices) -> str:
    """Pick a value for plan.ai_data[key] from `choices`, preferring values
    not yet used by sibling lessons in the same course. Stable per lesson."""
    ai = plan.ai_data or {}
    existing = ai.get(key)
    if existing in choices:
        return existing
    used = set()
    try:
        siblings = LessonPlan.objects.filter(course=plan.course).exclude(pk=plan.pk)
        for d in siblings.values_list('ai_data', flat=True):
            if isinstance(d, dict) and d.get(key) in choices:
                used.add(d[key])
    except Exception:
        pass
    available = [c for c in choices if c not in used] or list(choices)
    rng = random.Random(f"{key}-{plan.pk or 0}-{(plan.topic or '')[:32]}")
    pick = rng.choice(available)
    try:
        plan.ai_data = {**ai, key: pick}
        plan.save(update_fields=['ai_data'])
    except Exception:
        pass
    return pick


def _pick_design_variant(plan) -> str:
    return _pick_unique(plan, 'design_variant', DESIGN_VARIANTS)


def _pick_layout_pattern(plan) -> str:
    return _pick_unique(plan, 'layout_pattern', LAYOUT_PATTERNS)


def _is_special_slide(slide) -> bool:
    L = (slide.get('layout_type') or slide.get('layout') or '').lower()
    if L in _SPECIAL_LAYOUTS:
        return True
    T = (slide.get('title') or '').lower()
    return any(k in T for k in _SPECIAL_TITLE_KEYWORDS)


def _ensure_image_query(slide, plan):
    """Derive an image search query from slide title + lesson topic if missing,
    so layouts requesting an image have something to fetch."""
    if (slide.get('image_search_query') or slide.get('image_query')
            or slide.get('image_prompt')):
        return
    title = (slide.get('title') or '').strip()
    topic = (getattr(plan, 'topic', '') or '').strip()
    parts = [p for p in (title, topic) if p]
    if parts:
        slide['image_search_query'] = ' '.join(parts)[:120]


def _ensure_blocks(slide):
    """Build .blocks from .content for multi_block layouts when AI didn't supply them."""
    if slide.get('blocks'):
        return
    content = slide.get('content') or []
    if not isinstance(content, list):
        return
    blocks = []
    for c in content:
        if isinstance(c, dict):
            blocks.append(c)
        else:
            cs = str(c)
            if ' — ' in cs:
                h, *rest = cs.split(' — ')
                blocks.append({'heading': h.strip(),
                               'content': ' — '.join(rest).strip()})
            else:
                blocks.append({'heading': cs[:48], 'content': cs})
    if blocks:
        slide['blocks'] = blocks


def _apply_layout_pattern(slides, pattern, plan):
    """Rewrite the layout of non-special slides per the chosen pattern so each
    lesson arranges its key points and images differently. Returns a NEW list;
    the original ai_data is untouched (PPTX export keeps its source layouts)."""
    seq = _PATTERN_SEQUENCES.get(pattern) or ['content']
    out = []
    content_idx = 0
    # Stable per-lesson rotation so two lessons with the same pattern still differ.
    rotation = (plan.pk or 0) % len(seq)
    for s in slides:
        s = copy.deepcopy(s)
        if _is_special_slide(s):
            out.append(s)
            continue
        layout = seq[(content_idx + rotation) % len(seq)]
        s['layout'] = layout
        if layout in _IMAGE_LAYOUT_NAMES:
            _ensure_image_query(s, plan)
        elif layout == 'multi_block':
            _ensure_blocks(s)
        content_idx += 1
        out.append(s)
    return out


def _instructor_required(view_func):
    """Decorator: must be logged in + instructor role."""
    from functools import wraps
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_instructor:
            # For AJAX requests, return JSON error instead of HTML redirect
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'error': 'Instructor access required.'}, status=403)
            
            messages.error(request, "Instructor access required.")
            return redirect('accounts:login')
        return view_func(request, *args, **kwargs)
    return wrapper


# ─── Power Point Presentation Generator ─────────────────────────────────────────────────────────────

@_instructor_required
def check_quota_status(request, course_pk):
    """AJAX endpoint to check API quota status before generation."""
    from instaasys.quota_checker import check_api_quotas
    
    try:
        quota_status = check_api_quotas()
        return JsonResponse(quota_status)
    except Exception as e:
        logger.exception("Failed to check quota status")
        return JsonResponse({
            'status': 'error',
            'error': str(e),
            'can_generate': True  # Allow generation even if check fails
        })


@_instructor_required
def lesson_generate_from_plan(request, course_pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    
    # --- AJAX handling ---
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        try:
            selected_weeks = request.POST.getlist('selected_weeks')
            skip_blueprint = request.POST.get('skip_blueprint', 'false').lower() == 'true'
            use_pipeline   = request.POST.get('use_pipeline', 'false').lower() == 'true'
            slide_count = int(request.POST.get('slide_count', 10))
            depth = request.POST.get('depth', 'overview')

            if not selected_weeks:
                return JsonResponse({'plan_ids': [], 'error': 'No weeks selected'}, status=400)

            plan = _build_combined_plan(course, selected_weeks, slide_count=slide_count,
                                         depth=depth, use_pipeline=use_pipeline)
            if plan is None:
                return JsonResponse({'plan_ids': [], 'error': 'No valid weeks found'}, status=400)

            try:
                if skip_blueprint:
                    from .tasks import generate_lesson_task
                    logger.info(f"Queuing async Celery task for plan {plan.id} (skip blueprint)")
                    generate_lesson_task.delay(plan.id)
                else:
                    from .tasks import generate_blueprint_task
                    logger.info(f"Queuing async blueprint task for plan {plan.id}")
                    generate_blueprint_task.delay(plan.id)
            except Exception as celery_err:
                logger.warning(f"Celery unavailable, falling back to sync generation: {celery_err}")
                if skip_blueprint:
                    _generate_lesson_sync(plan)
                else:
                    _generate_blueprint_sync(plan)

            logger.info(f"Combined lesson plan {plan.id} created for course {course_pk}")
            return JsonResponse({'plan_ids': [plan.id]})

        except Exception as ajax_err:
            logger.exception(f"AJAX error in lesson_generate_from_plan: {str(ajax_err)}")
            return JsonResponse({'plan_ids': [], 'error': str(ajax_err)}, status=500)

    # --- Regular form POST (non-AJAX) ---
    if request.method == 'POST':
        selected_weeks = request.POST.getlist('selected_weeks')
        skip_blueprint = request.POST.get('skip_blueprint', 'false').lower() == 'true'
        use_pipeline   = request.POST.get('use_pipeline', 'false').lower() == 'true'
        slide_count = int(request.POST.get('slide_count', 10))
        depth = request.POST.get('depth', 'overview')

        if not selected_weeks:
            messages.error(request, "Please select at least one week.")
            return render(request, 'presentations/lesson_generate_from_plan.html',
                          _pipeline_status_context(course))

        try:
            plan = _build_combined_plan(course, selected_weeks, slide_count=slide_count,
                                         depth=depth, use_pipeline=use_pipeline)
            if plan is None:
                messages.warning(request, "No valid weeks found to generate.")
                return render(request, 'presentations/lesson_generate_from_plan.html',
                              _pipeline_status_context(course))

            try:
                if skip_blueprint:
                    from .tasks import generate_lesson_task
                    logger.info(f"Queuing async Celery task for plan {plan.id} (skip blueprint)")
                    generate_lesson_task.delay(plan.id)
                else:
                    from .tasks import generate_blueprint_task
                    logger.info(f"Queuing async blueprint task for plan {plan.id}")
                    generate_blueprint_task.delay(plan.id)
            except Exception as celery_err:
                logger.warning(f"Celery unavailable, falling back to sync generation: {celery_err}")
                if skip_blueprint:
                    _generate_lesson_sync(plan)
                else:
                    _generate_blueprint_sync(plan)

            if skip_blueprint:
                messages.success(request, "Generating your presentation... It will appear in your Lessons library shortly.")
            else:
                messages.success(request, "Generating blueprint... It will be ready for review shortly.")
            return redirect('lessons:lesson_list', course_pk=course_pk)

        except Exception as exc:
            logger.exception(f"Failed to generate lesson from plan for course {course_pk}: {str(exc)}")
            messages.error(request, f"Generation failed: {str(exc)[:100]}")
            return render(request, 'presentations/lesson_generate_from_plan.html',
                          _pipeline_status_context(course))
    
    return render(request, 'presentations/lesson_generate_from_plan.html',
                  _pipeline_status_context(course))


@_instructor_required
def lesson_list(request, course_pk):
    from django.core.paginator import Paginator as _Paginator
    from django.db.models import Q
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    plans_qs = course.lesson_plans.all().order_by('-id')

    # AJAX request: return JSON with filtering support
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # Search filter
        search_query = request.GET.get('q', '').strip()
        if search_query:
            plans_qs = plans_qs.filter(
                Q(topic__icontains=search_query) | 
                Q(objectives__icontains=search_query)
            )
        
        # Status filter
        status_filter = request.GET.get('status', '').strip()
        if status_filter:
            plans_qs = plans_qs.filter(status=status_filter)
        
        # Return JSON array of lessons
        lessons = [
            {
                'id': plan.id,
                'topic': plan.topic,
                'week_number': plan.week_number,
                'objectives': plan.objectives,
                'status': plan.status,
                'created_at': plan.created_at.isoformat(),
            }
            for plan in plans_qs
        ]
        
        return JsonResponse({'lessons': lessons})

    # Non-AJAX: render page with pagination
    paginator = _Paginator(plans_qs, 12)
    page_obj  = paginator.get_page(request.GET.get('page', 1))

    return render(request, 'presentations/lesson_list.html',
                  {'course': course, 'plans': page_obj})


@_instructor_required
def lesson_create(request, course_pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)

    if request.method == 'POST':
        form = LessonGenerateForm(request.POST)
        if form.is_valid():
            plan = form.save(commit=False)
            plan.course  = course
            plan.status  = LessonPlan.STATUS_PENDING

            # Store slide_count and depth so the async task can read them
            slide_count = int(request.POST.get('slide_count', 10))
            depth = request.POST.get('depth', 'overview')
            plan.ai_data = {'_meta': {'slide_count': slide_count, 'depth': depth}}
            plan.save()

            # Check skip_blueprint parameter (default to blueprint mode)
            skip_blueprint = request.POST.get('skip_blueprint', 'false').lower() == 'true'

            # Try async first; fall back to sync if Redis not available
            try:
                if skip_blueprint:
                    # Use existing direct generation
                    from .tasks import generate_lesson_task
                    generate_lesson_task.delay(plan.id)
                    messages.info(request,
                        "Lesson plan is being generated. Refresh in ~30 seconds.")
                else:
                    # Use new blueprint workflow
                    from .tasks import generate_blueprint_task
                    generate_blueprint_task.delay(plan.id)
                    messages.info(request,
                        "Blueprint is being generated. Refresh in ~30 seconds.")
            except Exception:
                if skip_blueprint:
                    _generate_lesson_sync(plan)
                    messages.success(request, "Lesson plan generated successfully!")
                else:
                    _generate_blueprint_sync(plan)
                    messages.success(request, "Blueprint generated successfully!")

            return redirect('lessons:lesson_detail', course_pk=course_pk, pk=plan.pk)
    else:
        form = LessonGenerateForm()

    return render(request, 'presentations/lesson_form.html',
                  {'form': form, 'course': course})


@_instructor_required
def lesson_create_from_weekly_plan(request, course_pk):
    """AJAX endpoint: Auto-create lesson from course's weekly plan data."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'})
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'})
    
    week_number = data.get('week_number')
    topics = data.get('topics', [])
    cilos = data.get('cilos', [])
    skip_blueprint = data.get('skip_blueprint', False)
    slide_count = int(data.get('slide_count', 10))
    depth = data.get('depth', 'overview')

    if not week_number:
        return JsonResponse({'success': False, 'error': 'Week number is required'})

    try:
        # Use first topic as lesson topic, or a generic title
        topic = topics[0] if topics else f"Week {week_number} Lesson"
        objectives = '\n'.join(cilos) if cilos else "Course learning outcomes"

        # Create LessonPlan with pending status
        plan = LessonPlan.objects.create(
            course=course,
            topic=topic,
            week_number=int(week_number),
            objectives=objectives,
            status=LessonPlan.STATUS_PENDING,
            ai_data={'_meta': {'slide_count': slide_count, 'depth': depth}},
        )
        
        # Try async first; fall back to sync if Redis not available
        try:
            if skip_blueprint:
                # Use existing direct generation
                from .tasks import generate_lesson_task
                generate_lesson_task.delay(plan.id)
            else:
                # Use new blueprint workflow (default)
                from .tasks import generate_blueprint_task
                generate_blueprint_task.delay(plan.id)
        except Exception:
            if skip_blueprint:
                _generate_lesson_sync(plan)
            else:
                _generate_blueprint_sync(plan)
        
        # Return success with plan ID
        return JsonResponse({
            'success': True,
            'plan_id': plan.id,
        })
    
    except Exception as exc:
        logger.exception("Failed to create lesson from weekly plan")
        return JsonResponse({'success': False, 'error': str(exc)})



def _pipeline_status_context(course):
    """Render context for the lesson generation page including AI Pipeline badges."""
    from instaasys.ai_service import get_provider_status
    from instaasys.ai_pipeline import PIPELINE_CONFIG
    from django.conf import settings

    provider_status = {p['name']: p for p in get_provider_status()}

    def _resolve(stage_name):
        cfg = PIPELINE_CONFIG.get(stage_name, {})
        primary  = cfg.get('primary')
        fallback = cfg.get('fallback')
        primary_state  = provider_status.get(primary)
        fallback_state = provider_status.get(fallback)
        if primary_state and primary_state.get('available'):
            return {'label': stage_name.title(), 'used': primary, 'fallback': None,
                    'ok': True, 'configured': True}
        if fallback_state and fallback_state.get('available'):
            return {'label': stage_name.title(), 'used': fallback, 'fallback': primary,
                    'ok': True, 'configured': True}
        if primary_state or fallback_state:
            return {'label': stage_name.title(), 'used': None,
                    'fallback': primary or fallback, 'ok': False, 'configured': True}
        return {'label': stage_name.title(), 'used': None, 'fallback': None,
                'ok': False, 'configured': False}

    pexels_ok   = bool(getattr(settings, 'PEXELS_API_KEY', ''))
    unsplash_ok = bool(getattr(settings, 'UNSPLASH_ACCESS_KEY', ''))
    if pexels_ok:
        images = {'label': 'Images', 'used': 'Pexels', 'fallback': None,
                  'ok': True, 'configured': True}
    elif unsplash_ok:
        images = {'label': 'Images', 'used': 'Unsplash', 'fallback': 'Pexels',
                  'ok': True, 'configured': True}
    else:
        images = {'label': 'Images', 'used': None, 'fallback': None,
                  'ok': False, 'configured': False}

    return {
        'course': course,
        'pipeline_stages': [
            _resolve('research'),
            _resolve('organize'),
            _resolve('polish'),
            images,
        ],
    }


def _build_combined_plan(course, selected_weeks, slide_count=10, depth='overview',
                         use_pipeline=False):
    """
    Collect topics and objectives from all selected weeks and create a single
    combined LessonPlan.  Multiple selected weeks produce ONE presentation
    rather than separate files.
    """
    all_topics = []
    all_cilos  = []
    week_nums  = []

    for week_value in selected_weeks:
        week_data = next(
            (w for w in course.weekly_plan if str(w.get('week')) == week_value), None
        )
        if not week_data:
            logger.debug(f"Week {week_value} not found in weekly_plan for course {course.pk}")
            continue

        for t in week_data.get('topics', []):
            if t and t not in all_topics:
                all_topics.append(t)

        for c in week_data.get('cilos', []):
            if c and c not in all_cilos:
                all_cilos.append(c)

        week_nums.append(int(week_value.split('-')[0]))

    if not week_nums:
        return None

    week_nums.sort()
    first_week = week_nums[0]

    # Build a readable week label: "Week 2" or "Weeks 2–4"
    if len(week_nums) == 1:
        week_label = f"Week {week_nums[0]}"
    else:
        week_label = f"Weeks {week_nums[0]}–{week_nums[-1]}"

    # Combine topics into a single display title (truncated to fit the DB field)
    if all_topics:
        combined_topic = ", ".join(all_topics)
        if len(combined_topic) > 295:
            combined_topic = combined_topic[:292] + "..."
    else:
        combined_topic = f"{week_label} Lesson"

    objectives = "\n".join(all_cilos) if all_cilos else "Course learning outcomes"

    logger.info(
        f"Creating combined LessonPlan for {course.code}: {week_label} | "
        f"Topics: {combined_topic[:80]}"
    )

    plan = LessonPlan.objects.create(
        course=course,
        topic=combined_topic,
        week_number=first_week,
        objectives=objectives,
        status=LessonPlan.STATUS_PENDING,
        # Store the full structured week info so the AI gets rich context
        ai_data={
            '_meta': {
                'week_label': week_label,
                'week_nums': week_nums,
                'topics_list': all_topics,
                'slide_count': slide_count,
                'depth': depth,
                'use_pipeline': bool(use_pipeline),
            }
        },
    )
    return plan


def _generate_lesson_sync(plan):
    """Synchronous fallback when Celery/Redis is unavailable."""
    from instaasys.ai_service import generate_lesson_outline
    from .pptx_builder import build_pptx, repair_ai_data
    from .tasks import _build_generation_stats
    from datetime import datetime as _dt
    try:
        course = plan.course
        meta   = (plan.ai_data or {}).get('_meta', {})
        if meta.get('use_pipeline'):
            from instaasys.ai_pipeline import generate_presentation
            ai_data = generate_presentation(
                course=course,
                week_data={
                    'week':   meta.get('week_label') or plan.week_number,
                    'topics': meta.get('topics_list') or [plan.topic],
                    'cilos':  [c for c in (plan.objectives or '').split('\n') if c.strip()],
                },
                slide_count=int(meta.get('slide_count', 10)),
                content_depth=meta.get('depth', 'overview'),
            )
            ai_meta = {
                'provider_used': 'pipeline',
                'model_used': 'multi-ai',
                'rate_limited': [],
                'pipeline_meta': ai_data.pop('_pipeline_meta', {}),
            }
        else:
            ai_data = generate_lesson_outline(
                topic=plan.topic,
                objectives=plan.objectives,
                syllabus=course.raw_text,
                week_number=plan.week_number,
                topics_list=meta.get('topics_list'),
                week_label=meta.get('week_label'),
            )
            ai_meta = ai_data.pop('_ai_meta', {})
        ai_data = repair_ai_data(ai_data)
        pptx_bytes, pptx_stats = build_pptx(ai_data, course=course, collect_stats=True)
        ai_data['_generation_stats'] = _build_generation_stats({'_ai_meta': ai_meta}, pptx_stats)
        plan.ai_data = ai_data
        filename     = f"lesson_w{plan.week_number}_{plan.id}.pptx"
        plan.pptx_file.save(filename, ContentFile(pptx_bytes), save=False)
        plan.status  = LessonPlan.STATUS_READY
        plan.save()
    except Exception as exc:
        plan.status    = LessonPlan.STATUS_FAILED
        plan.error_msg = str(exc)
        plan.save()
        raise


def _generate_blueprint_sync(plan):
    """Synchronous fallback for blueprint generation when Celery/Redis is unavailable."""
    from instaasys.ai_service import generate_lesson_blueprint
    from datetime import datetime
    try:
        course = plan.course
        meta = (plan.ai_data or {}).get('_meta', {})

        slide_count = meta.get('slide_count', 10)
        depth = meta.get('depth', 'overview')

        blueprint_data = generate_lesson_blueprint(
            topic=plan.topic,
            objectives=plan.objectives,
            syllabus=course.raw_text,
            week_number=plan.week_number,
            topics_list=meta.get('topics_list'),
            week_label=meta.get('week_label'),
            slide_count=slide_count,
            depth=depth,
        )

        ai_meta = blueprint_data.pop('_ai_meta', {})

        plan.ai_data = plan.ai_data or {}
        plan.ai_data['blueprint'] = blueprint_data
        plan.ai_data['blueprint']['metadata'] = {
            'generated_at': datetime.now().isoformat()
        }
        plan.ai_data['_generation_stats'] = {
            'generated_at': datetime.now().isoformat(),
            'provider_used': ai_meta.get('provider_used'),
            'model_used': ai_meta.get('model_used'),
            'rate_limited_providers': ai_meta.get('rate_limited', []),
        }
        plan.status = LessonPlan.STATUS_BLUEPRINT_PENDING
        plan.save()

        logger.info(f"Blueprint for plan {plan.id} generated successfully (sync).")
    except Exception as exc:
        logger.error(f"Blueprint generation for plan {plan.id} failed: {exc}")
        plan.status = LessonPlan.STATUS_FAILED
        plan.error_msg = str(exc)
        plan.save()
        raise


@_instructor_required
def lesson_detail(request, course_pk, pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    plan   = get_object_or_404(LessonPlan, pk=pk, course=course)

    # Check if lesson has blueprint data (blueprint-based workflow)
    # vs direct generation workflow (backward compatibility)
    has_blueprint = bool(plan.ai_data and plan.ai_data.get('blueprint'))

    # Determine the effective slide data to display based on workflow type
    ai = plan.ai_data or {}
    if has_blueprint:
        final = ai.get('final_slides', {}) or {}
        display_slides     = final.get('slides', [])
        display_objectives = final.get('objectives', [])
        display_title      = final.get('title', plan.topic)
    else:
        display_slides     = ai.get('slides', [])
        display_objectives = ai.get('objectives', [])
        display_title      = ai.get('title', plan.topic)

    generation_stats = ai.get('_generation_stats') or {}

    return render(request, 'presentations/lesson_detail.html', {
        'course': course,
        'plan': plan,
        'has_blueprint': has_blueprint,
        'display_slides': display_slides,
        'display_objectives': display_objectives,
        'display_title': display_title,
        'generation_stats': generation_stats,
    })


@_instructor_required
def lesson_update_content(request, course_pk, pk):
    """AJAX: Save edited slide content and rebuild the PPTX file."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    plan   = get_object_or_404(LessonPlan, pk=pk, course=course)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    ai_data = payload.get('ai_data', {})
    if not isinstance(ai_data, dict):
        return JsonResponse({'success': False, 'error': 'Bad format'}, status=400)

    # Check if lesson has blueprint or direct generation data
    has_blueprint = bool(plan.ai_data and plan.ai_data.get('blueprint'))
    
    # Merge into existing ai_data so we don't lose keys like 'week'
    merged = dict(plan.ai_data or {})
    
    if has_blueprint:
        # Blueprint-based lesson: Update final_slides
        merged.update({
            'final_slides': {
                'title':      ai_data.get('title',      merged.get('final_slides', {}).get('title', '')),
                'objectives': ai_data.get('objectives', merged.get('final_slides', {}).get('objectives', [])),
                'week':       merged.get('final_slides', {}).get('week', ''),
                'slides':     ai_data.get('slides',     merged.get('final_slides', {}).get('slides', [])),
            }
        })
        # Update topic if title changed
        if ai_data.get('title'):
            plan.topic = ai_data['title']
        
        # Use final_slides for PPTX rebuild
        pptx_data = merged['final_slides']
    else:
        # Direct generation lesson: Update slides directly (backward compatibility)
        merged.update({
            'title':      ai_data.get('title',      merged.get('title', '')),
            'objectives': ai_data.get('objectives', merged.get('objectives', [])),
            'slides':     ai_data.get('slides',     merged.get('slides', [])),
        })
        if merged.get('title'):
            plan.topic = merged['title']
        
        # Use merged data for PPTX rebuild
        pptx_data = merged
    
    plan.ai_data = merged
    plan.save()

    # Rebuild PPTX from updated content
    try:
        from .pptx_builder import build_pptx
        from django.core.files.base import ContentFile as CF
        pptx_bytes = build_pptx(pptx_data, course=course)
        filename   = f"lesson_w{plan.week_number}_{plan.id}.pptx"
        if plan.pptx_file:
            plan.pptx_file.delete(save=False)
        plan.pptx_file.save(filename, CF(pptx_bytes), save=True)
    except Exception as exc:
        logger.exception("PPTX rebuild failed after content edit")
        return JsonResponse({'success': True,
                             'warning': f'Saved, but PPTX rebuild failed: {exc}'})

    return JsonResponse({'success': True})


@_instructor_required
def lesson_delete(request, course_pk, pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    plan   = get_object_or_404(LessonPlan, pk=pk, course=course)
    if request.method == 'POST':
        plan.delete()
        messages.success(request, 'Lesson plan deleted.')
        return redirect('lessons:lesson_list', course_pk=course_pk)
    return render(request, 'presentations/lesson_confirm_delete.html',
                  {'course': course, 'plan': plan})


@_instructor_required
def lesson_download_pptx(request, course_pk, pk):
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    plan   = get_object_or_404(LessonPlan, pk=pk, course=course,
                                status=LessonPlan.STATUS_READY)
    if not plan.pptx_file:
        messages.error(request, "File not ready yet.")
        return redirect('lessons:lesson_detail', course_pk=course_pk, pk=pk)

    response = HttpResponse(
        plan.pptx_file.read(),
        content_type=(
            'application/vnd.openxmlformats-officedocument'
            '.presentationml.presentation'
        )
    )
    filename = f"{course.code}_Week{plan.week_number}_{plan.topic[:30]}.pptx"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@_instructor_required
def lesson_slideshow(request, course_pk, pk):
    """Standalone fullscreen web-based presentation."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    plan   = get_object_or_404(LessonPlan, pk=pk, course=course,
                                status=LessonPlan.STATUS_READY)
    
    # Determine the effective slide data based on workflow type
    ai = plan.ai_data or {}
    has_blueprint = bool(ai.get('blueprint'))
    
    if has_blueprint:
        final = ai.get('final_slides', {}) or {}
        slides = final.get('slides', [])
        objectives = final.get('objectives', [])
        title = final.get('title', plan.topic)
    else:
        slides = ai.get('slides', [])
        objectives = ai.get('objectives', [])
        title = ai.get('title', plan.topic)
    
    # Fallback: if no slides, create a basic title slide
    if not slides:
        slides = [{
            'title': title or plan.topic,
            'layout': 'title',
            'content': [],
            'notes': ''
        }]

    # ── Apply per-lesson layout pattern (transient — does not affect PPTX) ──
    design_variant = _pick_design_variant(plan)
    layout_pattern = _pick_layout_pattern(plan)
    slides = _apply_layout_pattern(slides, layout_pattern, plan)

    # ── Fetch image URLs for image-based layouts ──────────────────────────
    def _img_query(s):
        return (s.get('image_search_query') or s.get('image_query')
                or s.get('image_prompt') or '')
    def _layout(s):
        return s.get('layout_type') or s.get('layout') or ''
    needs_images = [
        s for s in slides
        if _layout(s) in _IMAGE_LAYOUT_NAMES and _img_query(s) and not s.get('image_url')
    ]
    if needs_images:
        from .pptx_builder import fetch_image_url_for_web
        def _resolve(slide):
            url = fetch_image_url_for_web(_img_query(slide))
            if url:
                slide['image_url'] = url
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(_resolve, needs_images))
        # NOTE: don't persist back to plan.ai_data — patterned layouts are
        # render-time only; the JS image API caches subsequent loads.

    palette = (plan.ai_data or {}).get('palette', {})
    palette_css = _build_palette_css(palette) if palette else ''

    return render(request, 'presentations/lesson_slideshow.html', {
        'course':          course,
        'plan':            plan,
        'slides_json':     json.dumps(slides),
        'objectives_json': json.dumps(objectives or []),
        'title_json':      json.dumps(title or plan.topic),
        'palette_css':     palette_css,
        'design_variant':  design_variant,
    })


@login_required
def lesson_image_url_api(request, course_pk):
    """Return a CDN image URL for a search query (used by slideshow JS to lazy-load photos)."""
    get_object_or_404(Course, pk=course_pk, instructor=request.user)
    q = request.GET.get('q', '').strip()
    if not q:
        return JsonResponse({'url': None})
    from .pptx_builder import fetch_image_url_for_web
    url = fetch_image_url_for_web(q)
    return JsonResponse({'url': url, 'failed': url is None})


@login_required
def lesson_status_api(request, pk):
    """Polling endpoint so the frontend can check generation status."""
    plan = get_object_or_404(LessonPlan, pk=pk,
                              course__instructor=request.user)
    return JsonResponse({'status': plan.status, 'error': plan.error_msg})


@_instructor_required
def lesson_blueprint_edit(request, course_pk, pk):
    """Display blueprint editor for review and editing."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    plan = get_object_or_404(LessonPlan, pk=pk, course=course)
    
    # Validate plan status is blueprint_pending or failed
    if plan.status not in [LessonPlan.STATUS_BLUEPRINT_PENDING, LessonPlan.STATUS_FAILED]:
        messages.warning(request, "Blueprint is not available for editing.")
        return redirect('lessons:lesson_detail', course_pk=course_pk, pk=pk)
    
    # Extract blueprint data from ai_data field
    blueprint = (plan.ai_data or {}).get('blueprint', {})
    
    # Handle missing blueprint data gracefully
    if not blueprint:
        messages.error(request, "No blueprint data found.")
        return redirect('lessons:lesson_detail', course_pk=course_pk, pk=pk)
    
    return render(request, 'presentations/blueprint_edit.html', {
        'course': course,
        'plan': plan,
        'blueprint': blueprint,
    })


@_instructor_required
def lesson_blueprint_update(request, course_pk, pk):
    """AJAX: Save edited blueprint data."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    plan = get_object_or_404(LessonPlan, pk=pk, course=course)
    
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)
    
    try:
        payload = json.loads(request.body)
        blueprint_data = payload.get('blueprint', {})
        
        # Validate blueprint structure
        if not isinstance(blueprint_data, dict) or 'slides' not in blueprint_data:
            return JsonResponse({'success': False, 'error': 'Invalid blueprint format'}, status=400)
        
        # Update blueprint in ai_data
        plan.ai_data = plan.ai_data or {}
        plan.ai_data['blueprint'] = blueprint_data
        
        # Update metadata['edited_at'] timestamp
        from datetime import datetime
        if 'metadata' not in plan.ai_data['blueprint']:
            plan.ai_data['blueprint']['metadata'] = {}
        plan.ai_data['blueprint']['metadata']['edited_at'] = datetime.now().isoformat()
        
        plan.save()
        
        return JsonResponse({'success': True})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as exc:
        logger.exception("Blueprint update failed")
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)


@_instructor_required
def lesson_blueprint_approve(request, course_pk, pk):
    """Approve blueprint and trigger PPTX generation."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    plan = get_object_or_404(LessonPlan, pk=pk, course=course)
    
    # Validate plan status is blueprint_pending
    if plan.status != LessonPlan.STATUS_BLUEPRINT_PENDING:
        messages.error(request, "Blueprint cannot be approved in current status.")
        return redirect('lessons:lesson_detail', course_pk=course_pk, pk=pk)
    
    # Update status and metadata
    from datetime import datetime
    plan.status = LessonPlan.STATUS_BLUEPRINT_APPROVED
    if 'blueprint' not in plan.ai_data:
        plan.ai_data['blueprint'] = {}
    if 'metadata' not in plan.ai_data['blueprint']:
        plan.ai_data['blueprint']['metadata'] = {}
    plan.ai_data['blueprint']['metadata']['approved_at'] = datetime.now().isoformat()
    plan.save()
    
    # Queue PPTX generation
    try:
        from .tasks import generate_pptx_from_blueprint_task
        generate_pptx_from_blueprint_task.delay(plan.id)
        messages.success(request, "Blueprint approved. Generating presentation...")
    except Exception as exc:
        # Fallback to sync generation
        logger.warning(f"Celery unavailable, falling back to sync generation: {exc}")
        _generate_pptx_from_blueprint_sync(plan)
        messages.success(request, "Presentation generated successfully!")
    
    return redirect('lessons:lesson_detail', course_pk=course_pk, pk=pk)


def _generate_pptx_from_blueprint_sync(plan):
    """Synchronous fallback for PPTX generation from blueprint when Celery/Redis is unavailable."""
    from .pptx_builder import build_pptx
    from .tasks import _blueprint_to_slides
    from datetime import datetime
    try:
        blueprint = plan.ai_data.get('blueprint', {})
        if not blueprint:
            raise ValueError("No blueprint data found")

        final_data = _blueprint_to_slides(blueprint)
        plan.ai_data['final_slides'] = final_data

        pptx_bytes, pptx_stats = build_pptx(final_data, course=plan.course, collect_stats=True)

        existing = plan.ai_data.get('_generation_stats', {})
        existing.update({
            'pptx_generated_at': datetime.now().isoformat(),
            'slides_total': pptx_stats.get('slides_total', 0),
            'images_fetched': pptx_stats.get('images_fetched', 0),
            'images_failed': pptx_stats.get('images_failed', 0),
            'image_sources': pptx_stats.get('image_sources', {}),
        })
        plan.ai_data['_generation_stats'] = existing

        filename = f"lesson_w{plan.week_number}_{plan.id}.pptx"
        plan.pptx_file.save(filename, ContentFile(pptx_bytes), save=False)
        plan.status = LessonPlan.STATUS_READY
        plan.save()

        logger.info(f"PPTX for plan {plan.id} generated from blueprint (sync).")
    except Exception as exc:
        logger.error(f"PPTX generation from blueprint failed for plan {plan.id}: {exc}")
        plan.status = LessonPlan.STATUS_FAILED
        plan.error_msg = str(exc)
        plan.save()
        raise


@_instructor_required
def lesson_blueprint_reorder(request, course_pk, pk):
    """AJAX: Reorder slides in the blueprint JSON."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    plan   = get_object_or_404(LessonPlan, pk=pk, course=course)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    try:
        payload   = json.loads(request.body)
        new_order = payload.get('order', [])   # list of original 0-based indices (strings or ints)
        new_order = [int(i) for i in new_order]

        blueprint = (plan.ai_data or {}).get('blueprint', {})
        slides    = blueprint.get('slides', [])

        if len(new_order) != len(slides):
            return JsonResponse({'success': False, 'error': 'Order length mismatch'}, status=400)

        reordered = [slides[i] for i in new_order if 0 <= i < len(slides)]
        # Re-number slides sequentially
        for idx, slide in enumerate(reordered):
            slide['slide_number'] = idx + 1

        plan.ai_data['blueprint']['slides'] = reordered
        plan.save()
        return JsonResponse({'success': True})
    except (json.JSONDecodeError, ValueError, IndexError) as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)


# ─── Manual Slide Builder ─────────────────────────────────────────────────────────────

@_instructor_required
def lesson_builder(request, course_pk):
    """Manual slide builder page."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    return render(request, 'presentations/lesson_builder.html', {'course': course})


@_instructor_required
def lesson_builder_generate(request, course_pk):
    """AJAX: generate slides from pasted text via AI (Gamma-style flow)."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=400)

    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)  # noqa: F841

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)

    text_content = (data.get('text_content') or '').strip()
    if not text_content:
        return JsonResponse({'success': False, 'error': 'No text provided'}, status=400)

    mode = data.get('mode', 'generate')
    week_number = int(data.get('week_number') or 1)
    topic = (data.get('topic') or '').strip()

    try:
        from instaasys.ai_service import generate_slides_from_text
        result = generate_slides_from_text(
            text_content=text_content,
            mode=mode,
            week_number=week_number,
            topic=topic,
        )
        return JsonResponse({'success': True, 'slides': result.get('slides', []),
                             'title': result.get('title', topic),
                             'week': result.get('week', str(week_number))})
    except Exception as e:
        logger.exception("lesson_builder_generate failed")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@_instructor_required
def lesson_builder_save(request, course_pk):
    """AJAX endpoint to save manually built slides."""
    try:
        if request.method != 'POST':
            return JsonResponse({'success': False, 'error': 'POST required'}, status=400)
        
        course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in request: {str(e)}")
            return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
        
        week_number = data.get('week_number', 1)
        # Ensure week_number is not null and is a valid integer
        if week_number is None:
            week_number = 1
        try:
            week_number = int(week_number)
            if week_number < 1:
                week_number = 1
        except (ValueError, TypeError):
            week_number = 1
        topic = data.get('topic', 'Untitled')
        slides = data.get('slides', [])
        theme = data.get('theme', 'Academic Blue')
        
        # Validate slides data
        if not slides:
            return JsonResponse({'success': False, 'error': 'No slides provided'}, status=400)
        
        # Extract objectives from the objectives slide
        objectives_list = []
        for slide in slides:
            if slide.get('layout') == 'objectives':
                objectives_list = slide.get('content', [])
                break
        objectives_text = '\n'.join(objectives_list)
        
        # Create the lesson plan
        plan = LessonPlan.objects.create(
            course=course,
            topic=topic,
            week_number=week_number,
            objectives=objectives_text,
            ai_data={
                'title': topic,
                'week': week_number,
                'objectives': objectives_list,
                'slides': slides,
                'theme': theme,
                'manual_build': True
            },
            status=LessonPlan.STATUS_READY
        )
        
        # Generate PPTX backup file
        try:
            from .pptx_builder import build_pptx
            lesson_data = {
                'title': topic,
                'week': week_number,
                'objectives': objectives_list,
                'slides': slides
            }
            pptx_bytes = build_pptx(lesson_data, course=course)
            filename = f"lesson_{plan.id}.pptx"
            plan.pptx_file.save(filename, ContentFile(pptx_bytes), save=True)
        except Exception as pptx_error:
            logger.error(f"PPTX generation failed for plan {plan.id}: {str(pptx_error)}", exc_info=True)
            # Don't fail the whole request if PPTX generation fails
            # The plan is still saved, just without the PPTX file
        
        logger.info(f"Manual lesson plan {plan.id} created for course {course_pk}")
        return JsonResponse({'success': True, 'plan_id': plan.id})
        
    except Exception as e:
        error_msg = f"Error saving manual lesson: {str(e)}"
        logger.exception(error_msg)
        # Return more detailed error for debugging
        import traceback
        detailed_error = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        return JsonResponse({'success': False, 'error': detailed_error}, status=500)


@_instructor_required
def lesson_builder_edit(request, course_pk, pk):
    """Edit an existing manually-built lesson."""
    course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
    plan = get_object_or_404(LessonPlan, pk=pk, course=course)
    return render(request, 'presentations/lesson_builder.html', {'course': course, 'plan': plan})


@_instructor_required
def lesson_builder_update(request, course_pk, pk):
    """AJAX endpoint to update existing lesson slides."""
    try:
        if request.method != 'POST':
            return JsonResponse({'success': False, 'error': 'POST required'}, status=400)
        
        course = get_object_or_404(Course, pk=course_pk, instructor=request.user)
        plan = get_object_or_404(LessonPlan, pk=pk, course=course)
        
        try:
            data = json.loads(request.body)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in request: {str(e)}")
            return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
        
        week_number = data.get('week_number', plan.week_number)
        # Ensure week_number is not null and is a valid integer
        if week_number is None:
            week_number = plan.week_number if plan.week_number else 1
        try:
            week_number = int(week_number)
            if week_number < 1:
                week_number = 1
        except (ValueError, TypeError):
            week_number = plan.week_number if plan.week_number else 1
        topic = data.get('topic', plan.topic)
        slides = data.get('slides', [])
        theme = data.get('theme', 'Academic Blue')
        
        # Validate slides data
        if not slides:
            return JsonResponse({'success': False, 'error': 'No slides provided'}, status=400)
        
        # Extract objectives from the objectives slide
        objectives_list = []
        for slide in slides:
            if slide.get('layout') == 'objectives':
                objectives_list = slide.get('content', [])
                break
        objectives_text = '\n'.join(objectives_list)
        
        # Update the lesson plan
        plan.topic = topic
        plan.week_number = week_number
        plan.objectives = objectives_text
        plan.ai_data = {
            'title': topic,
            'week': week_number,
            'objectives': objectives_list,
            'slides': slides,
            'theme': theme,
            'manual_build': True
        }
        plan.status = LessonPlan.STATUS_READY
        
        # Regenerate PPTX backup file
        try:
            from .pptx_builder import build_pptx
            lesson_data = {
                'title': topic,
                'week': week_number,
                'objectives': objectives_list,
                'slides': slides
            }
            pptx_bytes = build_pptx(lesson_data, course=course)
            filename = f"lesson_{plan.id}.pptx"
            plan.pptx_file.save(filename, ContentFile(pptx_bytes), save=True)
        except Exception as pptx_error:
            logger.error(f"PPTX generation failed for plan {plan.id}: {str(pptx_error)}", exc_info=True)
            # Don't fail the whole request if PPTX generation fails
        
        plan.save()
        
        logger.info(f"Manual lesson plan {plan.id} updated for course {course_pk}")
        return JsonResponse({'success': True, 'plan_id': plan.id})
        
    except Exception as e:
        error_msg = f"Error updating manual lesson: {str(e)}"
        logger.exception(error_msg)
        # Return more detailed error for debugging
        import traceback
        detailed_error = f"{str(e)}\n\nTraceback:\n{traceback.format_exc()}"
        return JsonResponse({'success': False, 'error': detailed_error}, status=500)

