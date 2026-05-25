from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect
from instaasys.views import ai_status, quota_status, theme_config_api, user_theme_preference

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/ai-status/', ai_status, name='ai_status'),
    path('api/quota-status/', quota_status, name='quota_status'),
    path('api/theme-config/', theme_config_api, name='theme_config'),
    path('api/user/theme-preference/', user_theme_preference, name='user_theme_preference'),
    path('presentations/', include('presentations.urls')),
    path('tos/', include('tos.urls')),
    path('assessments/', include('assessments.urls')),
    path('grading/', include('grading.urls')),
    path('attendance/', include('attendance.urls')),
    path('', include('accounts.urls')),  # Landing page at root
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)