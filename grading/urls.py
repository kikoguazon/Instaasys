from django.urls import path
from . import views

app_name = 'grading'

urlpatterns = [
    # Instructor
    path('course/<int:course_pk>/eclass-record/',
         views.eclass_record, name='eclass_record'),
    path('course/<int:course_pk>/eclass-record/autosave/',
         views.autosave_score, name='autosave_score'),
    path('course/<int:course_pk>/eclass-record/add-ww/',
         views.add_ww_column, name='add_ww_column'),
    path('course/<int:course_pk>/eclass-record/add-pt/',
         views.add_pt_column, name='add_pt_column'),
    path('course/<int:course_pk>/eclass-record/delete-ww/<int:col_num>/',
         views.delete_ww_column, name='delete_ww_column'),
    path('course/<int:course_pk>/eclass-record/delete-pt/<int:col_num>/',
         views.delete_pt_column, name='delete_pt_column'),
    path('course/<int:course_pk>/eclass-record/add-ao/',
         views.add_activity_column, name='add_activity_column'),
    path('course/<int:course_pk>/eclass-record/delete-ao/<int:col_num>/',
         views.delete_activity_column, name='delete_activity_column'),
    path('course/<int:course_pk>/midterm-sheet/',
         views.midterm_sheet, name='midterm_sheet'),
    path('course/<int:course_pk>/midterm-sheet/add-cs/',
         views.add_final_cs_column, name='add_final_cs_column'),
    path('course/<int:course_pk>/midterm-sheet/add-pt/',
         views.add_final_pt_column, name='add_final_pt_column'),
    path('course/<int:course_pk>/midterm-sheet/delete-cs/<int:col_num>/',
         views.delete_final_cs_column, name='delete_final_cs_column'),
    path('course/<int:course_pk>/midterm-sheet/delete-pt/<int:col_num>/',
         views.delete_final_pt_column, name='delete_final_pt_column'),
    path('course/<int:course_pk>/midterm-sheet/add-ao/',
         views.add_final_activity_column, name='add_final_activity_column'),
    path('course/<int:course_pk>/midterm-sheet/delete-ao/<int:col_num>/',
         views.delete_final_activity_column, name='delete_final_activity_column'),
    path('course/<int:course_pk>/midterm-sheet/autosave/',
         views.final_autosave_score, name='final_autosave_score'),
    path('course/<int:course_pk>/final-sheet/',
         views.final_sheet, name='final_sheet'),
    path('course/<int:course_pk>/grade-summary/',
         views.grade_summary, name='grade_summary'),
    path('course/<int:course_pk>/grade-management/',
         views.grade_management, name='grade_management'),
    path('course/<int:course_pk>/export/',
         views.export_grades_txt, name='export_grades'),

    # Student
    path('my-grades/',
         views.student_grades, name='student_grades'),
    path('my-grades/<int:course_pk>/',
         views.student_course_grades, name='student_course_grades'),
]