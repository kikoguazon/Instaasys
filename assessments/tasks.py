import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2)
def generate_questions_task(self, questionset_id: int, topic: str, bloom_level: str,
                             q_type: str, count: int, difficulty: str,
                             week_ref: str = '', presentation_content: str = '',
                             assessment_type: str = 'quiz'):
    from .models import Question, QuestionSet
    from accounts.models import Course
    from instaasys.ai_service import generate_questions

    logger.info(f"Starting question generation task: questionset_id={questionset_id}, topic='{topic}', bloom_level='{bloom_level}', q_type='{q_type}', count={count}, difficulty='{difficulty}', week_ref='{week_ref}', assessment_type='{assessment_type}'")
    
    qs = QuestionSet.objects.get(id=questionset_id)
    course = qs.course
    try:
        questions_data = generate_questions(
            topic=topic,
            bloom_level=bloom_level,
            q_type=q_type,
            count=int(count),
            course_title=course.title,
            difficulty=difficulty,
            presentation_content=presentation_content,
            assessment_type=assessment_type,
        )
        logger.info(f"Successfully generated {len(questions_data)} questions from AI service")
        created_ids = []
        for q in questions_data:
            obj = Question.objects.create(
                course        = course,
                question_set  = qs,
                topic         = topic,
                week_ref      = week_ref,
                question_type = q_type,
                bloom_level   = q.get('bloom_level', bloom_level),
                difficulty    = q.get('difficulty', difficulty),
                content       = q.get('content', ''),
                choices       = q.get('choices'),
                answer_key    = q.get('answer_key', ''),
                explanation   = q.get('explanation', ''),
                rubric        = q.get('rubric', ''),
                expected_answer = q.get('expected_answer', ''),
                follow_up     = q.get('follow_up', ''),
            )
            created_ids.append(obj.id)
        
        # Preserve FAILED state if a sibling task (same question set, other
        # q_type) already flagged the set as failed. Otherwise mark ready.
        fresh = QuestionSet.objects.get(id=questionset_id)
        if fresh.status != QuestionSet.STATUS_FAILED:
            fresh.status = QuestionSet.STATUS_READY
            fresh.save(update_fields=['status'])
        logger.info(f"Created {len(created_ids)} questions for set {questionset_id}")
        return created_ids
    except Exception as exc:
        logger.error(f"Question generation task failed: {exc}")
        qs.status = QuestionSet.STATUS_FAILED
        qs.error_msg = str(exc)
        qs.save()
        raise self.retry(exc=exc, countdown=10)