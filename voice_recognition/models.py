from django.db import models
from django.contrib.auth.models import User


class VoiceRecording(models.Model):
    """Model to store voice recordings and their transcriptions."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='voice_recordings')
    audio_file = models.FileField(upload_to='audio_recordings/')
    transcription = models.TextField(blank=True, null=True)
    language = models.CharField(max_length=10, default='en')
    is_emergency = models.BooleanField(default=False)
    confidence_score = models.FloatField(null=True, blank=True)
    keywords_detected = models.JSONField(default=list, blank=True)
    location = models.JSONField(null=True, blank=True)  # Store lat/lng
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Recording by {self.user.username} - {self.created_at}"


class EmergencyKeyword(models.Model):
    """Keywords that trigger emergency alerts."""
    keyword = models.CharField(max_length=100, unique=True)
    language = models.CharField(max_length=10, default='en')
    severity = models.IntegerField(default=1)  # 1-5 scale
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.keyword} ({self.language})"
