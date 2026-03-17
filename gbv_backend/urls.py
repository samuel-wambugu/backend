"""
URL configuration for GBV Backend project.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('users.auth_urls')),
    path('api/users/', include('users.urls')),
    path('api/voice/', include('voice_recognition.urls')),
    path('api/alerts/', include('alerts.urls')),
    path('api/sensors/', include('sensors.urls')),
    path('api/incidents/', include('incidents.urls')),
    path('api/ai/', include('ai_gateway.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
