from django.contrib import admin
from .models import TableOfSpecifications


@admin.register(TableOfSpecifications)
class TableOfSpecificationsAdmin(admin.ModelAdmin):
    list_display = ('id', 'course', 'exam_type', 'status', 'created_at')
    list_filter = ('status', 'exam_type', 'created_at')
    search_fields = ('course__title', 'exam_type')
    readonly_fields = ('created_at', 'tos_data', 'xlsx_file')
