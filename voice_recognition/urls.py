from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import VoiceRecordingViewSet, EmergencyKeywordViewSet

router = DefaultRouter()
router.register(r'recordings', VoiceRecordingViewSet, basename='recording')
router.register(r'keywords', EmergencyKeywordViewSet, basename='keyword')

urlpatterns = [
    path('', include(router.urls)),
]
