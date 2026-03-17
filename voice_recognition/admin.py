from django.contrib import admin
from .models import VoiceRecording, EmergencyKeyword


@admin.register(VoiceRecording)
class VoiceRecordingAdmin(admin.ModelAdmin):
    list_display = ['user', 'language', 'is_emergency', 'confidence_score', 'created_at']
    list_filter = ['is_emergency', 'language', 'processed']
    search_fields = ['user__username', 'transcription']
    readonly_fields = ['transcription', 'confidence_score', 'keywords_detected']


@admin.register(EmergencyKeyword)
class EmergencyKeywordAdmin(admin.ModelAdmin):
    list_display = ['keyword', 'language', 'severity', 'is_active']
    list_filter = ['language', 'severity', 'is_active']
    search_fields = ['keyword']
