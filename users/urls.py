from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    UserProfileViewSet,
    SafeLocationViewSet,
    register,
)

router = DefaultRouter()
router.register(r'profiles', UserProfileViewSet, basename='profile')
router.register(r'safe-locations', SafeLocationViewSet, basename='safe-location')

urlpatterns = [
    path('register/', register, name='register'),
    path('', include(router.urls)),
]
