from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AlertViewSet, EmergencyContactViewSet, SafeCheckInViewSet, LiveSafetySessionViewSet

router = DefaultRouter()
router.register(r'alerts', AlertViewSet, basename='alert')
router.register(r'contacts', EmergencyContactViewSet, basename='contact')
router.register(r'checkins', SafeCheckInViewSet, basename='checkin')
router.register(r'live-sessions', LiveSafetySessionViewSet, basename='live-session')

urlpatterns = [
    path('', include(router.urls)),
]
