from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SensorDeviceViewSet, SensorReadingViewSet, SensorAlertViewSet

router = DefaultRouter()
router.register(r'devices', SensorDeviceViewSet, basename='device')
router.register(r'readings', SensorReadingViewSet, basename='reading')
router.register(r'rules', SensorAlertViewSet, basename='rule')

urlpatterns = [
    path('', include(router.urls)),
]
