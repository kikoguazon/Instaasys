import logging
from celery import shared_task
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2)
def generate_tos_task(self, tos_id: int):
    from .models import TableOfSpecifications
    from instaasys.ai_service import generate_tos
    from .tos_builder import build_tos_xlsx

    tos = TableOfSpecifications.objects.get(id=tos_id)
    try:
        ai_data = generate_tos(
            topics=tos.topics_data,
            total_items=tos.total_items,
            exam_type=tos.exam_type,
            course_title=tos.course.title,
        )
        tos.tos_data = ai_data
        xlsx_bytes = build_tos_xlsx(ai_data)
        filename = f"tos_{tos.exam_type.replace(' ', '_')}_{tos.id}.xlsx"
        tos.xlsx_file.save(filename, ContentFile(xlsx_bytes), save=False)
        tos.status = 'ready'
        tos.save()
        logger.info(f"TOS {tos_id} generated successfully.")
    except Exception as exc:
        logger.error(f"TOS {tos_id} failed: {exc}")
        tos.status = 'failed'
        tos.error_msg = str(exc)
        tos.save()
        raise self.retry(exc=exc, countdown=10)
