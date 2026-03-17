from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import SensorDevice, SensorReading, SensorAlert
from .serializers import (
    SensorDeviceSerializer, SensorReadingSerializer,
    SensorAlertSerializer, SensorDataInputSerializer
)
from .services import SensorService


class SensorDeviceViewSet(viewsets.ModelViewSet):
    """ViewSet for sensor devices."""
    queryset = SensorDevice.objects.all()
    serializer_class = SensorDeviceSerializer
    
    def get_queryset(self):
        """Filter devices by current user."""
        return self.queryset.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        """Create sensor device for current user."""
        serializer.save(user=self.request.user)
    
    @action(detail=True, methods=['get'])
    def statistics(self, request, pk=None):
        """Get statistics for a sensor device."""
        device = self.get_object()
        service = SensorService()
        stats = service.get_device_statistics(device.device_id)
        
        return Response(stats)
    
    @action(detail=True, methods=['post'])
    def toggle_active(self, request, pk=None):
        """Toggle device active status."""
        device = self.get_object()
        device.is_active = not device.is_active
        device.save()
        
        return Response({
            'status': 'active' if device.is_active else 'inactive',
            'device_id': device.device_id
        })


class SensorReadingViewSet(viewsets.ModelViewSet):
    """ViewSet for sensor readings."""
    queryset = SensorReading.objects.all()
    serializer_class = SensorReadingSerializer
    
    def get_queryset(self):
        """Filter readings by current user's devices."""
        return self.queryset.filter(device__user=self.request.user)
    
    @action(detail=False, methods=['post'])
    def submit(self, request):
        """Submit new sensor reading."""
        serializer = SensorDataInputSerializer(data=request.data)
        
        if serializer.is_valid():
            service = SensorService()
            result = service.process_sensor_reading(
                device_id=serializer.validated_data['device_id'],
                value=serializer.validated_data['value'],
                raw_data=serializer.validated_data.get('raw_data'),
                location=serializer.validated_data.get('location')
            )
            
            if result['success']:
                return Response(result, status=status.HTTP_201_CREATED)
            else:
                return Response(result, status=status.HTTP_400_BAD_REQUEST)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'])
    def anomalies(self, request):
        """Get all anomalous readings."""
        readings = self.get_queryset().filter(is_anomaly=True)
        serializer = self.get_serializer(readings, many=True)
        return Response(serializer.data)


class SensorAlertViewSet(viewsets.ModelViewSet):
    """ViewSet for sensor alert rules."""
    queryset = SensorAlert.objects.all()
    serializer_class = SensorAlertSerializer
    
    def get_queryset(self):
        """Filter alert rules by current user's devices."""
        return self.queryset.filter(device__user=self.request.user)
