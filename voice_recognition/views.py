from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from .models import VoiceRecording, EmergencyKeyword
from .serializers import VoiceRecordingSerializer, EmergencyKeywordSerializer
import logging
from typing import Any, cast

logger = logging.getLogger(__name__)


def _dispatch_voice_task(task_name: str, recording_id: int) -> None:
    """Queue a voice-related Celery task with a broker-safe synchronous fallback."""
    from gbv_backend.celery import app as celery_app
    from .tasks import process_voice_recording, notify_emergency_contacts_of_recording

    task_map = {
        'voice_recognition.tasks.process_voice_recording': process_voice_recording,
        'voice_recognition.tasks.notify_emergency_contacts_of_recording': notify_emergency_contacts_of_recording,
    }
    task_fn = task_map.get(task_name)
    try:
        celery_app.send_task(task_name, args=[recording_id])
    except Exception as exc:
        logger.exception(
            'voice_task_async_dispatch_failed',
            extra={'task': task_name, 'recording_id': recording_id, 'error': str(exc)},
        )
        if task_fn is not None:
            cast(Any, task_fn).apply(args=[recording_id], throw=False)


class VoiceRecordingViewSet(viewsets.ModelViewSet):
    """ViewSet for voice recordings."""
    queryset = VoiceRecording.objects.all()
    serializer_class = VoiceRecordingSerializer
    parser_classes = (MultiPartParser, FormParser)
    
    def get_queryset(self):
        """Filter recordings by current user."""
        return self.queryset.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        """Save recording and trigger async processing."""
        recording = serializer.save(user=self.request.user)

        # Trigger async processing (broker-safe: falls back to inline if Redis is down)
        _dispatch_voice_task('voice_recognition.tasks.process_voice_recording', recording.id)
        # Immediately notify emergency contacts with the recording link
        _dispatch_voice_task('voice_recognition.tasks.notify_emergency_contacts_of_recording', recording.id)
    
    @action(detail=True, methods=['post'])
    def reprocess(self, request, pk=None):
        """Reprocess a voice recording."""
        recording = self.get_object()
        _dispatch_voice_task('voice_recognition.tasks.process_voice_recording', recording.id)
        return Response({
            'status': 'processing',
            'message': 'Voice recording is being reprocessed'
        })
    
    @action(detail=False, methods=['get'])
    def emergency(self, request):
        """Get all emergency recordings."""
        recordings = self.get_queryset().filter(is_emergency=True)
        serializer = self.get_serializer(recordings, many=True)
        return Response(serializer.data)


class EmergencyKeywordViewSet(viewsets.ModelViewSet):
    """ViewSet for emergency keywords."""
    queryset = EmergencyKeyword.objects.all()
    serializer_class = EmergencyKeywordSerializer
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get all active keywords."""
        keywords = self.queryset.filter(is_active=True)
        serializer = self.get_serializer(keywords, many=True)
        return Response(serializer.data)
