from django.contrib import admin
from .models import Question


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display  = ['content_preview', 'course', 'week_ref',
                     'question_type', 'bloom_level', 'difficulty', 'created_at']
    list_filter   = ['question_type', 'bloom_level', 'difficulty', 'course']
    search_fields = ['content', 'topic']

    def content_preview(self, obj):
        return obj.content[:60]
    content_preview.short_description = 'Question'