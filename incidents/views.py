from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from .models import Incident, IncidentEvidence, IncidentComment, IncidentJournalEntry
from alerts.models import Alert, SafeCheckIn, LiveSafetySession
from .serializers import (
    IncidentSerializer,
    IncidentEvidenceSerializer,
    IncidentCommentSerializer,
    IncidentJournalEntrySerializer,
    IncidentJournalEntryCreateSerializer,
)


class IncidentViewSet(viewsets.ModelViewSet):
    """ViewSet for incidents."""
    queryset = Incident.objects.all()
    serializer_class = IncidentSerializer
    
    def get_queryset(self):
        """Filter incidents by user or public incidents."""
        if self.request.user.is_staff:
            return self.queryset.all()
        return (
            self.queryset.filter(reporter=self.request.user) |
            self.queryset.filter(is_public=True)
        ).distinct().order_by('-created_at')
    
    def perform_create(self, serializer):
        """Create incident for current user."""
        serializer.save(reporter=self.request.user)
    
    @action(detail=True, methods=['post'])
    def add_comment(self, request, pk=None):
        """Add comment to incident."""
        incident = self.get_object()
        serializer = IncidentCommentSerializer(data=request.data)
        
        if serializer.is_valid():
            serializer.save(
                incident=incident,
                user=request.user,
                is_staff_comment=request.user.is_staff
            )
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'], parser_classes=[MultiPartParser, FormParser])
    def add_evidence(self, request, pk=None):
        """Add evidence to incident."""
        incident = self.get_object()
        
        # Check permission
        if incident.reporter != request.user and not request.user.is_staff:
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = IncidentEvidenceSerializer(data=request.data)
        
        if serializer.is_valid():
            serializer.save(incident=incident)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        """Update incident status (staff only)."""
        if not request.user.is_staff:
            return Response(
                {'error': 'Staff permission required'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        incident = self.get_object()
        new_status = request.data.get('status')
        
        if new_status in dict(Incident.STATUS_CHOICES).keys():
            incident.status = new_status
            incident.save()
            return Response({'status': 'success', 'new_status': new_status})
        
        return Response(
            {'error': 'Invalid status'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    @action(detail=False, methods=['get'])
    def my_incidents(self, request):
        """Get current user's incidents."""
        incidents = self.queryset.filter(reporter=request.user)
        serializer = self.get_serializer(incidents, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def recent(self, request):
        """Get recent public incidents."""
        incidents = self.queryset.filter(is_public=True).order_by('-created_at')[:10]
        serializer = self.get_serializer(incidents, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def timeline(self, request, pk=None):
        """Build a risk timeline for one incident using linked records."""
        incident = self.get_object()
        events = []

        events.append({
            'timestamp': incident.created_at.isoformat(),
            'type': 'incident_reported',
            'title': 'Incident reported',
            'details': incident.title,
            'risk_level': self._risk_level_from_severity(incident.severity),
        })

        for comment in incident.comments.select_related('user').all():
            events.append({
                'timestamp': comment.created_at.isoformat(),
                'type': 'comment',
                'title': 'Case comment',
                'details': comment.comment,
                'risk_level': 'medium',
                'actor': comment.user.username,
            })

        for evidence in incident.evidence.all():
            events.append({
                'timestamp': evidence.uploaded_at.isoformat(),
                'type': 'evidence',
                'title': f'Evidence added ({evidence.evidence_type})',
                'details': evidence.description or evidence.file.name,
                'risk_level': 'medium',
            })

        for entry in incident.journal_entries.select_related('author').all():
            events.append({
                'timestamp': entry.created_at.isoformat(),
                'type': 'journal',
                'title': 'Journal entry',
                'details': entry.note,
                'risk_level': entry.risk_level,
                'actor': entry.author.username,
                'tags': entry.tags,
            })

        for audit in incident.ai_audit_records.all()[:30]:
            payload = audit.response_payload or {}
            events.append({
                'timestamp': audit.created_at.isoformat(),
                'type': 'ai_triage',
                'title': 'AI triage update',
                'details': f"Urgency: {payload.get('urgency', 'n/a')}; Risk score: {payload.get('risk_score', 'n/a')}",
                'risk_level': self._risk_level_from_urgency(payload.get('urgency')),
            })

        linked_alert_ids = []
        if incident.alert_id:
            linked_alert_ids.append(incident.alert_id)

        linked_alerts = Alert.objects.filter(id__in=linked_alert_ids)
        if incident.voice_recording_id:
            linked_alerts = (linked_alerts | Alert.objects.filter(voice_recording_id=incident.voice_recording_id)).distinct()

        for alert in linked_alerts:
            events.append({
                'timestamp': alert.created_at.isoformat(),
                'type': 'alert',
                'title': f'Alert triggered ({alert.alert_type})',
                'details': alert.message,
                'risk_level': self._risk_level_from_priority(alert.priority),
            })

        for checkin in SafeCheckIn.objects.filter(user=incident.reporter, escalated_alert__in=linked_alerts):
            events.append({
                'timestamp': checkin.updated_at.isoformat(),
                'type': 'checkin',
                'title': 'Safe check-in escalation',
                'details': checkin.title,
                'risk_level': 'high' if checkin.status == 'missed' else 'medium',
            })

        for session in LiveSafetySession.objects.filter(user=incident.reporter, escalated_alert__in=linked_alerts):
            events.append({
                'timestamp': session.updated_at.isoformat(),
                'type': 'live_session',
                'title': 'Live safety session escalation',
                'details': session.title,
                'risk_level': 'critical' if session.status == 'escalated' else 'medium',
            })

        events.sort(key=lambda item: item['timestamp'])
        return Response({'incident_id': incident.id, 'events': events})

    @action(detail=True, methods=['get', 'post'])
    def journal(self, request, pk=None):
        """List/create private case journal entries for an incident."""
        incident = self.get_object()

        if incident.reporter != request.user and not request.user.is_staff:
            return Response({'error': 'Permission denied'}, status=status.HTTP_403_FORBIDDEN)

        if request.method.lower() == 'get':
            serializer = IncidentJournalEntrySerializer(incident.journal_entries.all(), many=True)
            return Response(serializer.data)

        serializer = IncidentJournalEntryCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        entry = serializer.save(incident=incident, author=request.user)
        return Response(IncidentJournalEntrySerializer(entry).data, status=status.HTTP_201_CREATED)

    def _risk_level_from_severity(self, severity):
        if severity >= 5:
            return 'critical'
        if severity >= 4:
            return 'high'
        if severity >= 2:
            return 'medium'
        return 'low'

    def _risk_level_from_priority(self, priority):
        if priority >= 5:
            return 'critical'
        if priority >= 4:
            return 'high'
        if priority >= 2:
            return 'medium'
        return 'low'

    def _risk_level_from_urgency(self, urgency):
        if urgency == 'critical':
            return 'critical'
        if urgency == 'high':
            return 'high'
        if urgency == 'medium':
            return 'medium'
        return 'low'
