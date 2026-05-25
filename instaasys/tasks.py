from celery import shared_task
from instaasys.ai_service import generate_lesson_outline
from .pptx_builder import build_pptx
from .models import LessonPlan
from django.core.files.base import ContentFile

@shared_task
def generate_lesson_async(plan_id: int, syllabus: str):
    plan = LessonPlan.objects.get(id=plan_id)
    data = generate_lesson_outline(plan.topic, plan.objectives, syllabus)
    pptx_bytes = build_pptx(data)
    plan.pptx_file.save(f"lesson_{plan_id}.pptx", ContentFile(pptx_bytes))
    plan.status = 'ready'
    plan.save()