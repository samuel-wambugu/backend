from rest_framework import serializers
from .models import SensorDevice, SensorReading, SensorAlert


class SensorDeviceSerializer(serializers.ModelSerializer):
    """Serializer for sensor devices."""
    
    class Meta:
        model = SensorDevice
        fields = [
            'id', 'device_id', 'sensor_type', 'name', 'is_active',
            'threshold_value', 'metadata', 'last_reading', 'created_at'
        ]


class SensorReadingSerializer(serializers.ModelSerializer):
    """Serializer for sensor readings."""
    device_name = serializers.CharField(source='device.name', read_only=True)
    sensor_type = serializers.CharField(source='device.sensor_type', read_only=True)
    
    class Meta:
        model = SensorReading
        fields = [
            'id', 'device', 'device_name', 'sensor_type', 'value',
            'raw_data', 'location', 'is_anomaly', 'alert_triggered', 'timestamp'
        ]


class SensorAlertSerializer(serializers.ModelSerializer):
    """Serializer for sensor alert rules."""
    
    class Meta:
        model = SensorAlert
        fields = [
            'id', 'device', 'condition', 'threshold',
            'alert_message', 'is_active', 'priority', 'created_at'
        ]


class SensorDataInputSerializer(serializers.Serializer):
    """Serializer for incoming sensor data."""
    device_id = serializers.CharField(max_length=100)
    value = serializers.FloatField()
    raw_data = serializers.JSONField(required=False)
    location = serializers.JSONField(required=False)
