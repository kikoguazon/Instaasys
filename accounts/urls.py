from django.urls import path, include
from django.contrib.auth import views as auth_views
from . import views

app_name = 'accounts'

urlpatterns = [
    # Landing & About
    path('',       views.landing_view, name='landing'),
    path('about/', views.about_view,   name='about'),
    
    # Auth
    path('login/',     views.login_view,    name='login'),
    path('logout/',    views.logout_view,   name='logout'),
    path('register/',  views.register_view, name='register'),  # shows disabled page
    path('dashboard/', views.dashboard,     name='dashboard'),
    
    # Password Reset
    path('password-reset/', 
         auth_views.PasswordResetView.as_view(
             template_name='accounts/password_reset.html',
             email_template_name='accounts/password_reset_email.html',
             subject_template_name='accounts/password_reset_subject.txt',
             success_url='/accounts/password-reset/done/'
         ), 
         name='password_reset'),
    path('password-reset/done/', 
         auth_views.PasswordResetDoneView.as_view(
             template_name='accounts/password_reset_done.html'
         ), 
         name='password_reset_done'),
    path('password-reset-confirm/<uidb64>/<token>/', 
         auth_views.PasswordResetConfirmView.as_view(
             template_name='accounts/password_reset_confirm.html',
             success_url='/accounts/password-reset-complete/'
         ), 
         name='password_reset_confirm'),
    path('password-reset-complete/', 
         auth_views.PasswordResetCompleteView.as_view(
             template_name='accounts/password_reset_complete.html'
         ), 
         name='password_reset_complete'),

    # Instructor
    path('instructor/',              views.instructor_dashboard, name='instructor_dashboard'),
    path('courses/',                 views.course_list,          name='course_list'),
    path('courses/upload/',          views.syllabus_upload,      name='syllabus_upload'),   # ← replaces /new/
    path('courses/create-from-syllabus/', views.course_create_from_syllabus, name='course_create_from_syllabus'),
    path('courses/join/',            views.join_course_via_code, name='join_course'),
    path('courses/<int:pk>/',        views.course_detail,        name='course_detail'),
    path('courses/<int:pk>/edit/',   views.course_edit,          name='course_edit'),
    path('courses/<int:pk>/delete/', views.course_delete,        name='course_delete'),
    path('courses/<int:pk>/enroll/', views.enroll_students,      name='enroll_students'),
    path('courses/<int:pk>/regenerate-code/', views.regenerate_join_code, name='regenerate_join_code'),
    path('courses/<int:pk>/enroll/add-student/', views.ajax_add_student, name='ajax_add_student'),
    path('courses/<int:pk>/confirm/', views.course_confirm,     name='course_confirm'),
    path('courses/<int:pk>/reupload/', views.course_reupload,   name='course_reupload'),

    # Students (instructor-managed)
    path('students/',              views.manage_students,    name='manage_students'),
    path('students/create/',       views.create_student,     name='create_student'),
    path('students/upload-csv/',   views.upload_students_csv, name='upload_students_csv'),

    # Profile
    path('profile/', views.profile_view, name='profile'),

    # Student
    path('student/', views.student_dashboard, name='student_dashboard'),

    # ── Admin Portal ────────────────────────────────────────────────────────
    path('portal/',                         views.portal_dashboard,  name='portal_dashboard'),
    path('portal/users/',                   views.portal_users,      name='portal_users'),
    path('portal/users/create/',            views.portal_create_user,name='portal_create_user'),
    path('portal/users/<int:pk>/edit/',     views.portal_edit_user,  name='portal_edit_user'),
    path('portal/users/<int:pk>/delete/',   views.portal_delete_user,name='portal_delete_user'),
    path('portal/courses/',                 views.portal_courses,    name='portal_courses'),
    path('portal/logs/',                    views.portal_logs,       name='portal_logs'),
    path('portal/django-admin/',            views.portal_django_admin, name='portal_django_admin'),

    # Notifications API
    path('api/notifications/', views.notifications_api, name='notifications_api'),
]