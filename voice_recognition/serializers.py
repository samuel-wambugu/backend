from rest_framework import serializers
from .models import VoiceRecording, EmergencyKeyword


class VoiceRecordingSerializer(serializers.ModelSerializer):
    """Serializer for voice recordings."""
    
    class Meta:
        model = VoiceRecording
        fields = [
            'id', 'audio_file', 'transcription', 'language',
            'is_emergency', 'confidence_score', 'keywords_detected',
            'location', 'created_at', 'processed'
        ]
        read_only_fields = [
            'transcription', 'is_emergency', 'confidence_score',
            'keywords_detected', 'processed'
        ]


class EmergencyKeywordSerializer(serializers.ModelSerializer):
    """Serializer for emergency keywords."""
    
    class Meta:
        model = EmergencyKeyword
        fields = ['id', 'keyword', 'language', 'severity', 'is_active']
