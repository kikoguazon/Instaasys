from django.urls import path
from . import views

app_name = 'tos'

urlpatterns = [
    path('course/<int:course_pk>/tos/',
         views.tos_list, name='tos_list'),
    path('course/<int:course_pk>/tos/new/',
         views.tos_create, name='tos_create'),
    # Returns the course's weekly plan topics as JSON for the TOS form
    path('course/<int:course_pk>/tos/syllabus-topics/',
         views.tos_syllabus_topics_api, name='tos_syllabus_topics_api'),
    path('course/<int:course_pk>/tos/<int:pk>/',
         views.tos_detail, name='tos_detail'),
    path('course/<int:course_pk>/tos/<int:pk>/delete/',
         views.tos_delete, name='tos_delete'),
    path('course/<int:course_pk>/tos/<int:pk>/download/',
         views.tos_download, name='tos_download'),
    path('tos/<int:pk>/status/',
         views.tos_status_api, name='tos_status_api'),
]
