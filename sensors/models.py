from django.db import models
from django.contrib.auth.models import User


class SensorDevice(models.Model):
    """Sensor device registered to a user."""
    SENSOR_TYPES = (
        ('accelerometer', 'Accelerometer'),
        ('gyroscope', 'Gyroscope'),
        ('gps', 'GPS'),
        ('proximity', 'Proximity'),
        ('sound', 'Sound Level'),
        ('heartrate', 'Heart Rate'),
        ('button', 'Panic Button'),
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sensor_devices')
    device_id = models.CharField(max_length=100, unique=True)
    sensor_type = models.CharField(max_length=20, choices=SENSOR_TYPES)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    threshold_value = models.FloatField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    last_reading = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.name} ({self.sensor_type}) - {self.user.username}"


class SensorReading(models.Model):
    """Individual sensor reading/event."""
    device = models.ForeignKey(SensorDevice, on_delete=models.CASCADE, related_name='readings')
    value = models.FloatField()
    raw_data = models.JSONField(default=dict, blank=True)
    location = models.JSONField(null=True, blank=True)  # lat/lng
    is_anomaly = models.BooleanField(default=False)
    alert_triggered = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['device', '-timestamp']),
        ]
    
    def __str__(self):
        return f"{self.device.sensor_type} - {self.value} at {self.timestamp}"


class SensorAlert(models.Model):
    """Predefined sensor alert rules."""
    device = models.ForeignKey(SensorDevice, on_delete=models.CASCADE, related_name='alert_rules')
    condition = models.CharField(max_length=20)  # greater_than, less_than, equals
    threshold = models.FloatField()
    alert_message = models.TextField()
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=3)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.device.name} - {self.condition} {self.threshold}"
