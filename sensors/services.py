from django.db import models

from .models import SensorDevice, SensorReading, SensorAlert
from alerts.models import Alert
from gbv_backend.celery import app as celery_app


class SensorService:
    """Service for processing sensor data."""
    
    def process_sensor_reading(self, device_id, value, raw_data=None, location=None):
        """
        Process a new sensor reading and check for alerts.
        
        Args:
            device_id: Sensor device ID
            value: Sensor reading value
            raw_data: Additional sensor data
            location: Location data (lat/lng)
            
        Returns:
            dict: Processing result
        """
        try:
            device = SensorDevice.objects.get(device_id=device_id, is_active=True)
            
            # Create sensor reading
            reading = SensorReading.objects.create(
                device=device,
                value=value,
                raw_data=raw_data or {},
                location=location
            )
            
            # Update device last reading
            device.last_reading = reading.timestamp
            device.save()
            
            # Check for anomalies
            is_anomaly = self._check_anomaly(device, value)
            reading.is_anomaly = is_anomaly
            
            # Check alert rules
            alert_triggered = self._check_alert_rules(device, reading)
            
            if alert_triggered:
                reading.alert_triggered = True
                reading.save()
                
                # Create and send alert
                alert = Alert.objects.create(
                    user=device.user,
                    alert_type='sensor',
                    message=f"Sensor alert: {device.name} detected unusual activity",
                    location=location,
                    priority=5,
                    sensor_reading=reading
                )
                celery_app.send_task('alerts.tasks.send_emergency_alert', args=[alert.id])
                celery_app.send_task(
                    'ai_gateway.tasks.auto_triage_latest_incident_for_user',
                    args=[device.user_id, True, '', 'sensor_alert'],
                )
            
            reading.save()
            
            return {
                'success': True,
                'reading_id': reading.id,
                'is_anomaly': is_anomaly,
                'alert_triggered': alert_triggered
            }
            
        except SensorDevice.DoesNotExist:
            return {
                'success': False,
                'error': 'Device not found or inactive'
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def _check_anomaly(self, device, value):
        """
        Check if reading value is anomalous.
        
        Args:
            device: SensorDevice instance
            value: Reading value
            
        Returns:
            bool: True if anomalous
        """
        if not device.threshold_value:
            return False
        
        # Simple threshold-based detection
        # Can be enhanced with ML models
        if device.sensor_type == 'accelerometer':
            # High acceleration = possible fall or struggle
            return value > device.threshold_value
        elif device.sensor_type == 'sound':
            # Loud sound = possible scream
            return value > device.threshold_value
        elif device.sensor_type == 'heartrate':
            # Elevated heart rate = stress
            return value > device.threshold_value
        elif device.sensor_type == 'button':
            # Panic button pressed
            return value == 1
        
        return False
    
    def _check_alert_rules(self, device, reading):
        """
        Check if reading triggers any alert rules.
        
        Args:
            device: SensorDevice instance
            reading: SensorReading instance
            
        Returns:
            bool: True if alert should be triggered
        """
        rules = SensorAlert.objects.filter(device=device, is_active=True)
        
        for rule in rules:
            if self._evaluate_condition(rule.condition, reading.value, rule.threshold):
                return True
        
        return False
    
    def _evaluate_condition(self, condition, value, threshold):
        """Evaluate alert condition."""
        if condition == 'greater_than':
            return value > threshold
        elif condition == 'less_than':
            return value < threshold
        elif condition == 'equals':
            return value == threshold
        return False
    
    def get_device_statistics(self, device_id):
        """Get statistics for a sensor device."""
        try:
            device = SensorDevice.objects.get(device_id=device_id)
            readings = SensorReading.objects.filter(device=device)
            
            return {
                'total_readings': readings.count(),
                'anomalies': readings.filter(is_anomaly=True).count(),
                'alerts_triggered': readings.filter(alert_triggered=True).count(),
                'last_reading': device.last_reading,
                'average_value': readings.aggregate(models.Avg('value'))['value__avg']
            }
        except SensorDevice.DoesNotExist:
            return None
