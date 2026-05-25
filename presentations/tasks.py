import logging
from datetime import datetime
from celery import shared_task
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)


def _build_generation_stats(ai_data: dict, pptx_stats: dict) -> dict:
    """Assemble a generation_stats dict from AI metadata and PPTX image stats."""
    ai_meta = ai_data.get('_ai_meta', {})
    return {
        'generated_at': datetime.now().isoformat(),
        'provider_used': ai_meta.get('provider_used'),
        'model_used': ai_meta.get('model_used'),
        'rate_limited_providers': ai_meta.get('rate_limited', []),
        'slides_total': pptx_stats.get('slides_total', 0),
        'images_fetched': pptx_stats.get('images_fetched', 0),
        'images_failed': pptx_stats.get('images_failed', 0),
        'image_sources': pptx_stats.get('image_sources', {}),
    }


@shared_task(bind=True, max_retries=2)
def generate_blueprint_task(self, plan_id: int):
    """Generate blueprint data and save to LessonPlan."""
    from .models import LessonPlan
    from instaasys.ai_service import generate_lesson_blueprint

    plan = LessonPlan.objects.get(id=plan_id)
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

        # Store AI provider metadata for display
        ai_meta = blueprint_data.pop('_ai_meta', {})

        plan.ai_data = plan.ai_data or {}
        plan.ai_data['blueprint'] = blueprint_data
        plan.ai_data['blueprint']['metadata'] = {
            'generated_at': datetime.now().isoformat()
        }
        # Store lightweight generation stats (no image info yet — PPTX not built)
        plan.ai_data['_generation_stats'] = {
            'generated_at': datetime.now().isoformat(),
            'provider_used': ai_meta.get('provider_used'),
            'model_used': ai_meta.get('model_used'),
            'rate_limited_providers': ai_meta.get('rate_limited', []),
        }
        plan.status = LessonPlan.STATUS_BLUEPRINT_PENDING
        plan.save()

        logger.info(f"Blueprint for plan {plan_id} generated successfully.")
    except Exception as exc:
        logger.error(f"Blueprint generation for plan {plan_id} failed: {exc}")
        plan.status = LessonPlan.STATUS_FAILED
        plan.error_msg = str(exc)
        plan.save()
        raise self.retry(exc=exc, countdown=10)


def _blueprint_to_slides(blueprint: dict) -> dict:
    """
    Convert blueprint structure to format expected by build_pptx().

    Maps:
    - explanation -> content (wrapped in list)
    - image_prompt -> image_query
    - layout_type -> layout

    Preserves: title, notes, slide_number, visual_style, theme
    """
    final_data = {
        'title': blueprint.get('title', ''),
        'objectives': blueprint.get('objectives', []),
        'week': blueprint.get('week', ''),
        'theme': blueprint.get('theme', 'academic_blue'),  # Preserve theme
        'slides': []
    }

    for slide in blueprint.get('slides', []):
        explanation = slide.get('explanation', '')
        converted_slide = {
            'slide_number': slide.get('slide_number'),
            'layout': slide.get('layout_type', 'content'),
            'title': slide.get('title', ''),
            'content': [explanation] if explanation else [],
            'image_query': slide.get('image_prompt', ''),
            'notes': slide.get('notes', ''),
        }

        if 'visual_style' in slide:
            converted_slide['visual_style'] = slide['visual_style']
        
        if 'icon' in slide:
            converted_slide['icon'] = slide['icon']

        final_data['slides'].append(converted_slide)

    return final_data


@shared_task(bind=True, max_retries=2)
def generate_pptx_from_blueprint_task(self, plan_id: int):
    """Generate PPTX from approved blueprint data."""
    from .models import LessonPlan
    from .pptx_builder import build_pptx

    plan = LessonPlan.objects.get(id=plan_id)
    try:
        blueprint = plan.ai_data.get('blueprint', {})
        if not blueprint:
            raise ValueError("No blueprint data found")

        # Convert blueprint to final slide format
        final_data = _blueprint_to_slides(blueprint)
        plan.ai_data['final_slides'] = final_data

        # Generate PPTX and collect image fetch stats
        pptx_bytes, pptx_stats = build_pptx(final_data, course=plan.course, collect_stats=True)

        # Merge image stats into generation_stats
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

        logger.info(f"PPTX for plan {plan_id} generated from blueprint.")
    except Exception as exc:
        logger.error(f"PPTX generation from blueprint failed for plan {plan_id}: {exc}")
        plan.status = LessonPlan.STATUS_FAILED
        plan.error_msg = str(exc)
        plan.save()
        raise self.retry(exc=exc, countdown=10)


@shared_task(bind=True, max_retries=2)
def generate_lesson_task(self, plan_id: int):
    from .models import LessonPlan
    from instaasys.ai_service import generate_lesson_outline
    from .pptx_builder import build_pptx, repair_ai_data

    plan = LessonPlan.objects.get(id=plan_id)
    try:
        course = plan.course
        meta   = (plan.ai_data or {}).get('_meta', {})

        if meta.get('use_pipeline'):
            # Multi-AI pipeline path — research → organize → polish
            from instaasys.ai_pipeline import generate_presentation
            week_data = {
                'week':   meta.get('week_label') or plan.week_number,
                'topics': meta.get('topics_list') or [plan.topic],
                'cilos':  [c for c in (plan.objectives or '').split('\n') if c.strip()],
            }
            ai_data = generate_presentation(
                course=course,
                week_data=week_data,
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

        ai_data['_generation_stats'] = _build_generation_stats(
            {'_ai_meta': ai_meta}, pptx_stats
        )

        plan.ai_data = ai_data
        filename = f"lesson_w{plan.week_number}_{plan.id}.pptx"
        plan.pptx_file.save(filename, ContentFile(pptx_bytes), save=False)
        plan.status = LessonPlan.STATUS_READY
        plan.save()
        logger.info(f"Lesson plan {plan_id} generated successfully.")
    except Exception as exc:
        logger.error(f"Lesson plan {plan_id} failed: {exc}")
        plan.status = LessonPlan.STATUS_FAILED
        plan.error_msg = str(exc)
        plan.save()
        raise self.retry(exc=exc, countdown=10)
