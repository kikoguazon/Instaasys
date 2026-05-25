from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html
from django.urls import reverse
from django.contrib import messages
from .models import User, Course, Enrollment, SystemLog


# ─── User Admin ───────────────────────────────────────────────────────────────

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display  = ['username', 'full_name', 'email', 'role_badge',
                     'department', 'student_id', 'employee_id', 'is_active']
    list_filter   = ['role', 'is_active', 'is_staff', 'department']
    search_fields = ['username', 'first_name', 'last_name', 'email',
                     'student_id', 'employee_id']
    ordering      = ['role', 'last_name']
    list_per_page = 30

    fieldsets = UserAdmin.fieldsets + (
        ('INSTAASYS Role & IDs', {
            'fields': ('role', 'department', 'employee_id', 'student_id'),
        }),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'password1', 'password2'),
        }),
        ('Personal info', {
            'fields': ('first_name', 'last_name', 'email'),
        }),
        ('INSTAASYS Role & IDs', {
            'fields': ('role', 'department', 'employee_id', 'student_id'),
        }),
    )

    actions = ['make_instructor', 'make_student', 'deactivate_users', 'activate_users']

    @admin.display(description='Name')
    def full_name(self, obj):
        return obj.get_full_name() or obj.username

    @admin.display(description='Role')
    def role_badge(self, obj):
        if obj.is_superuser:
            return format_html(
                '<span style="background:#fef3c7;color:#92400e;padding:.2rem .6rem;'
                'border-radius:6px;font-size:.75rem;font-weight:700;">Admin</span>'
            )
        if obj.role == User.ROLE_INSTRUCTOR:
            return format_html(
                '<span style="background:#ede9fe;color:#5b21b6;padding:.2rem .6rem;'
                'border-radius:6px;font-size:.75rem;font-weight:700;">Instructor</span>'
            )
        return format_html(
            '<span style="background:#dcfce7;color:#166534;padding:.2rem .6rem;'
            'border-radius:6px;font-size:.75rem;font-weight:700;">Student</span>'
        )

    @admin.action(description='Set selected users to Instructor role')
    def make_instructor(self, request, queryset):
        updated = queryset.filter(is_superuser=False).update(role=User.ROLE_INSTRUCTOR)
        self.message_user(request, f'{updated} user(s) set to Instructor.', messages.SUCCESS)

    @admin.action(description='Set selected users to Student role')
    def make_student(self, request, queryset):
        updated = queryset.filter(is_superuser=False).update(role=User.ROLE_STUDENT)
        self.message_user(request, f'{updated} user(s) set to Student.', messages.SUCCESS)

    @admin.action(description='Deactivate selected users')
    def deactivate_users(self, request, queryset):
        updated = queryset.filter(is_superuser=False).update(is_active=False)
        self.message_user(request, f'{updated} user(s) deactivated.', messages.WARNING)

    @admin.action(description='Activate selected users')
    def activate_users(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} user(s) activated.', messages.SUCCESS)


# ─── Enrollment Inline ────────────────────────────────────────────────────────

class EnrollmentInline(admin.TabularInline):
    model      = Enrollment
    extra      = 0
    fields     = ['student', 'enrolled_at']
    readonly_fields = ['enrolled_at']
    raw_id_fields = ['student']


# ─── Course Admin ─────────────────────────────────────────────────────────────

@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display  = ['code', 'title', 'program', 'instructor_name',
                     'block', 'semester', 'school_year', 'student_count', 'status_badge']
    list_filter   = ['semester', 'school_year', 'program', 'status', 'instructor']
    search_fields = ['title', 'code', 'instructor__username',
                     'instructor__first_name', 'instructor__last_name']
    ordering      = ['-created_at']
    list_per_page = 25
    inlines       = [EnrollmentInline]

    fieldsets = (
        ('Identification', {
            'fields': ('code', 'title', 'program', 'instructor', 'status'),
        }),
        ('Schedule', {
            'fields': ('semester', 'school_year', 'block', 'time_frame'),
        }),
        ('Details', {
            'fields': ('prerequisite', 'credit_units', 'hours', 'description'),
            'classes': ('collapse',),
        }),
        ('Grading', {
            'fields': ('cs_weight', 'req_weight', 'exam_weight',
                       'requirement_max', 'midterm_max', 'final_max'),
        }),
    )

    @admin.display(description='Instructor')
    def instructor_name(self, obj):
        return obj.instructor.get_full_name() or obj.instructor.username

    @admin.display(description='Students')
    def student_count(self, obj):
        return obj.enrollments.count()

    @admin.display(description='Status')
    def status_badge(self, obj):
        colors = {
            'pending':   ('#e0f2fe', '#0369a1'),
            'draft':     ('#fef3c7', '#92400e'),
            'confirmed': ('#dcfce7', '#166534'),
            'ready':     ('#ede9fe', '#5b21b6'),
            'failed':    ('#fee2e2', '#991b1b'),
        }
        bg, fg = colors.get(obj.status, ('#f1f5f9', '#475569'))
        return format_html(
            '<span style="background:{};color:{};padding:.2rem .55rem;'
            'border-radius:6px;font-size:.75rem;font-weight:700;">{}</span>',
            bg, fg, obj.get_status_display()
        )


# ─── Enrollment Admin ─────────────────────────────────────────────────────────

@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display  = ['student_name', 'course', 'enrolled_at']
    list_filter   = ['course__semester', 'course__school_year', 'course']
    search_fields = ['student__username', 'student__first_name',
                     'student__last_name', 'course__code', 'course__title']
    ordering      = ['-enrolled_at']

    @admin.display(description='Student')
    def student_name(self, obj):
        return obj.student.get_full_name() or obj.student.username


# ─── System Log Admin ─────────────────────────────────────────────────────────

@admin.register(SystemLog)
class SystemLogAdmin(admin.ModelAdmin):
    list_display  = ['timestamp', 'action_badge', 'actor', 'target', 'ip_address']
    list_filter   = ['action', 'timestamp']
    search_fields = ['actor__username', 'target', 'detail', 'ip_address']
    readonly_fields = ['actor', 'action', 'target', 'detail', 'ip_address', 'timestamp']
    ordering      = ['-timestamp']
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    @admin.display(description='Action')
    def action_badge(self, obj):
        color_map = {
            'login':             ('#dcfce7', '#166534'),
            'logout':            ('#f1f5f9', '#475569'),
            'login_failed':      ('#fee2e2', '#991b1b'),
            'create_student':    ('#eef2ff', '#3730a3'),
            'create_instructor': ('#ede9fe', '#5b21b6'),
            'create_admin':      ('#fef3c7', '#92400e'),
            'delete_user':       ('#fee2e2', '#991b1b'),
            'delete_course':     ('#fee2e2', '#991b1b'),
            'grade_update':      ('#fdf4ff', '#6d28d9'),
            'attendance':        ('#ecfeff', '#0e7490'),
        }
        bg, fg = color_map.get(obj.action, ('#f8fafc', '#475569'))
        return format_html(
            '<span style="background:{};color:{};padding:.2rem .55rem;'
            'border-radius:6px;font-size:.75rem;font-weight:700;">{}</span>',
            bg, fg, obj.get_action_display()
        )


# ─── Admin site customisation ─────────────────────────────────────────────────

admin.site.site_header = 'INSTAASYS Administration'
admin.site.site_title  = 'INSTAASYS Admin'
admin.site.index_title = 'System Management'
