from django.urls import path
from . import views

app_name = 'assessments'

urlpatterns = [
    # Top-level QuestionSets
    path('course/<int:course_pk>/assessments/', 
         views.questionset_list, name='questionset_list'),
    path('course/<int:course_pk>/assessments/generate/', 
         views.question_generate, name='question_generate'),
    path('course/<int:course_pk>/assessments/<int:pk>/', 
         views.questionset_detail, name='questionset_detail'),
    path('course/<int:course_pk>/assessments/<int:pk>/delete/', 
         views.questionset_delete, name='questionset_delete'),
    path('course/<int:course_pk>/assessments/<int:pk>/export/', 
         views.questionset_export, name='questionset_export'),
    path('course/<int:course_pk>/assessments/<int:pk>/export-docx/',
         views.questionset_export_docx, name='questionset_export_docx'),
    path('course/<int:course_pk>/assessments/<int:pk>/export-md/',
         views.questionset_export_markdown, name='questionset_export_markdown'),
    path('course/<int:course_pk>/assessments/<int:pk>/preview/',
         views.questionset_preview, name='questionset_preview'),
    path('assessments/<int:pk>/status/', 
         views.questionset_status_api, name='questionset_status_api'),
         
    # Individual Questions
    path('course/<int:course_pk>/questions/<int:pk>/',
         views.question_detail, name='question_detail'),
    path('course/<int:course_pk>/questions/<int:pk>/edit/',
         views.question_edit, name='question_edit'),
    path('course/<int:course_pk>/questions/<int:pk>/delete/',
         views.question_delete, name='question_delete'),
    path('course/<int:course_pk>/questions/<int:pk>/inline-update/',
         views.question_inline_update, name='question_inline_update'),
    path('course/<int:course_pk>/questions/<int:pk>/regenerate/',
         views.question_regenerate_item, name='question_regenerate_item'),
]