from django.urls import path
from . import views

app_name = 'attendance'

urlpatterns = [
    # Instructor
    path('course/<int:course_pk>/attendance/',
         views.attendance_list, name='attendance_list'),
    path('course/<int:course_pk>/attendance/new/',
         views.attendance_create, name='attendance_create'),
    path('course/<int:course_pk>/attendance/<int:session_pk>/mark/',
         views.attendance_mark, name='attendance_mark'),
    path('course/<int:course_pk>/attendance/<int:session_pk>/delete/',
         views.attendance_delete, name='attendance_delete'),
    path('course/<int:course_pk>/attendance/summary/',
         views.attendance_summary, name='attendance_summary'),
    path('course/<int:course_pk>/attendance/export/',
         views.attendance_export, name='attendance_export'),

    # Student
    path('my-attendance/<int:course_pk>/',
         views.student_attendance, name='student_attendance'),
]
