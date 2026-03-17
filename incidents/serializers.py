from rest_framework import serializers
from django.conf import settings
from .models import Incident, IncidentEvidence, IncidentComment, IncidentJournalEntry


class IncidentEvidenceSerializer(serializers.ModelSerializer):
    """Serializer for incident evidence."""

    ALLOWED_EXTENSIONS = {
        'photo': {'.jpg', '.jpeg', '.png', '.webp'},
        'video': {'.mp4', '.mov', '.avi', '.mkv'},
        'audio': {'.wav', '.mp3', '.m4a', '.aac', '.ogg'},
        'document': {'.pdf', '.txt', '.doc', '.docx'},
    }
    
    class Meta:
        model = IncidentEvidence
        fields = ['id', 'evidence_type', 'file', 'description', 'uploaded_at']

    def validate(self, attrs):
        evidence_type = attrs.get('evidence_type')
        upload = attrs.get('file')

        if not upload or not evidence_type:
            return attrs

        extension = f".{upload.name.rsplit('.', 1)[-1].lower()}" if '.' in upload.name else ''
        allowed_extensions = self.ALLOWED_EXTENSIONS.get(evidence_type, set())
        if extension not in allowed_extensions:
            raise serializers.ValidationError({
                'file': f'Invalid file type for {evidence_type}. Allowed: {sorted(allowed_extensions)}'
            })

        max_size_mb = getattr(settings, 'MAX_EVIDENCE_FILE_SIZE_MB', 20)
        max_size_bytes = max_size_mb * 1024 * 1024
        if upload.size > max_size_bytes:
            raise serializers.ValidationError({
                'file': f'File too large. Maximum size is {max_size_mb}MB.'
            })

        return attrs


class IncidentCommentSerializer(serializers.ModelSerializer):
    """Serializer for incident comments."""
    username = serializers.CharField(source='user.username', read_only=True)
    
    class Meta:
        model = IncidentComment
        fields = ['id', 'user', 'username', 'comment', 'is_staff_comment', 'created_at']
        read_only_fields = ['user', 'is_staff_comment']


class IncidentSerializer(serializers.ModelSerializer):
    """Serializer for incidents."""
    evidence = IncidentEvidenceSerializer(many=True, read_only=True)
    comments = IncidentCommentSerializer(many=True, read_only=True)
    reporter_username = serializers.CharField(source='reporter.username', read_only=True)
    
    class Meta:
        model = Incident
        fields = [
            'id', 'reporter', 'reporter_username', 'title', 'description',
            'incident_date', 'location', 'location_description',
            'status', 'severity', 'is_anonymous', 'is_public',
            'voice_recording', 'alert', 'evidence', 'comments',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['reporter', 'status']
    
    def to_representation(self, instance):
        """Hide reporter info if anonymous."""
        data = super().to_representation(instance)
        if instance.is_anonymous:
            data['reporter_username'] = 'Anonymous'
            data['reporter'] = None
        return data


class IncidentJournalEntrySerializer(serializers.ModelSerializer):
    author_username = serializers.CharField(source='author.username', read_only=True)

    class Meta:
        model = IncidentJournalEntry
        fields = [
            'id',
            'incident',
            'author',
            'author_username',
            'note',
            'risk_level',
            'tags',
            'created_at',
        ]
        read_only_fields = ['incident', 'author', 'author_username', 'created_at']


class IncidentJournalEntryCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = IncidentJournalEntry
        fields = ['note', 'risk_level', 'tags']
