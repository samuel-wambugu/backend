from django.contrib import admin
from .models import SensorDevice, SensorReading, SensorAlert


@admin.register(SensorDevice)
class SensorDeviceAdmin(admin.ModelAdmin):
    list_display = ['name', 'sensor_type', 'user', 'is_active', 'last_reading']
    list_filter = ['sensor_type', 'is_active']
    search_fields = ['name', 'device_id', 'user__username']


@admin.register(SensorReading)
class SensorReadingAdmin(admin.ModelAdmin):
    list_display = ['device', 'value', 'is_anomaly', 'alert_triggered', 'timestamp']
    list_filter = ['is_anomaly', 'alert_triggered', 'device__sensor_type']
    search_fields = ['device__name']


@admin.register(SensorAlert)
class SensorAlertAdmin(admin.ModelAdmin):
    list_display = ['device', 'condition', 'threshold', 'priority', 'is_active']
    list_filter = ['condition', 'is_active', 'priority']
    search_fields = ['device__name']
