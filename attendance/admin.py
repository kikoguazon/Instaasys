from django.contrib import admin
from .models import AttendanceSession, AttendanceRecord


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display = ('course', 'date', 'present_count', 'absent_count')
    list_filter = ('course', 'date')


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ('session', 'enrollment', 'status')
    list_filter = ('status', 'session__date')
