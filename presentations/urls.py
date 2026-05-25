from django.urls import path
from . import views

app_name = 'lessons'

urlpatterns = [
    # Lesson Plans
    path('course/<int:course_pk>/lessons/',
         views.lesson_list, name='lesson_list'),
    path('course/<int:course_pk>/lessons/generate/',
         views.lesson_generate_from_plan, name='lesson_generate_from_plan'),
    path('course/<int:course_pk>/lessons/check-quota/',
         views.check_quota_status, name='check_quota_status'),
    path('course/<int:course_pk>/lessons/new/',
         views.lesson_create, name='lesson_create'),
    path('course/<int:course_pk>/lessons/from-weekly-plan/',
         views.lesson_create_from_weekly_plan, name='lesson_create_from_weekly_plan'),
    path('course/<int:course_pk>/lessons/<int:pk>/',
         views.lesson_detail, name='lesson_detail'),
    path('course/<int:course_pk>/lessons/<int:pk>/delete/',
         views.lesson_delete, name='lesson_delete'),
    path('course/<int:course_pk>/lessons/<int:pk>/update-content/',
         views.lesson_update_content, name='lesson_update_content'),
    path('course/<int:course_pk>/lessons/<int:pk>/slideshow/',
         views.lesson_slideshow, name='lesson_slideshow'),
    path('course/<int:course_pk>/lessons/<int:pk>/download/',
         views.lesson_download_pptx, name='lesson_download'),
    path('course/<int:course_pk>/lessons/<int:pk>/blueprint/edit/',
         views.lesson_blueprint_edit, name='lesson_blueprint_edit'),
    path('course/<int:course_pk>/lessons/<int:pk>/blueprint/update/',
         views.lesson_blueprint_update, name='lesson_blueprint_update'),
    path('course/<int:course_pk>/lessons/<int:pk>/blueprint/approve/',
         views.lesson_blueprint_approve, name='lesson_blueprint_approve'),
    path('course/<int:course_pk>/lessons/<int:pk>/blueprint/reorder/',
         views.lesson_blueprint_reorder, name='lesson_blueprint_reorder'),
    path('<int:pk>/status/',
         views.lesson_status_api, name='lesson_status_api'),
    
    # Manual Slide Builder
    path('course/<int:course_pk>/lessons/builder/',
         views.lesson_builder, name='lesson_builder'),
    path('course/<int:course_pk>/lessons/builder/generate/',
         views.lesson_builder_generate, name='lesson_builder_generate'),
    path('course/<int:course_pk>/lessons/builder/save/',
         views.lesson_builder_save, name='lesson_builder_save'),
    path('course/<int:course_pk>/lessons/<int:pk>/edit/',
         views.lesson_builder_edit, name='lesson_builder_edit'),
    path('course/<int:course_pk>/lessons/<int:pk>/edit/save/',
         views.lesson_builder_update, name='lesson_builder_update'),

    # Image URL proxy (used by slideshow JS)
    path('course/<int:course_pk>/image-url/',
         views.lesson_image_url_api, name='lesson_image_url_api'),
]