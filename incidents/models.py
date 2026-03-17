from django.db import models
from django.contrib.auth.models import User


class Incident(models.Model):
    """GBV incident report."""
    STATUS_CHOICES = (
        ('reported', 'Reported'),
        ('under_review', 'Under Review'),
        ('verified', 'Verified'),
        ('resolved', 'Resolved'),
        ('closed', 'Closed'),
    )
    
    SEVERITY_CHOICES = (
        (1, 'Low'),
        (2, 'Medium'),
        (3, 'High'),
        (4, 'Critical'),
        (5, 'Emergency'),
    )
    
    reporter = models.ForeignKey(User, on_delete=models.CASCADE, related_name='incidents')
    title = models.CharField(max_length=200)
    description = models.TextField()
    incident_date = models.DateTimeField()
    location = models.JSONField(null=True, blank=True)  # lat/lng
    location_description = models.TextField(blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='reported')
    severity = models.IntegerField(choices=SEVERITY_CHOICES, default=3)
    
    # Privacy
    is_anonymous = models.BooleanField(default=False)
    is_public = models.BooleanField(default=False)
    
    # Related records
    voice_recording = models.ForeignKey(
        'voice_recognition.VoiceRecording',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    alert = models.ForeignKey(
        'alerts.Alert',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} - {self.reporter.username if not self.is_anonymous else 'Anonymous'}"


class IncidentEvidence(models.Model):
    """Evidence attached to an incident."""
    EVIDENCE_TYPES = (
        ('photo', 'Photo'),
        ('video', 'Video'),
        ('audio', 'Audio'),
        ('document', 'Document'),
    )
    
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name='evidence')
    evidence_type = models.CharField(max_length=20, choices=EVIDENCE_TYPES)
    file = models.FileField(upload_to='incident_evidence/')
    description = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.evidence_type} - {self.incident.title}"


class IncidentComment(models.Model):
    """Comments/updates on incidents."""
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    comment = models.TextField()
    is_staff_comment = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['created_at']
    
    def __str__(self):
        return f"Comment on {self.incident.title} by {self.user.username}"


class IncidentJournalEntry(models.Model):
    """Private case journal entry linked to one incident."""

    RISK_LEVEL_CHOICES = (
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('critical', 'Critical'),
    )

    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name='journal_entries')
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name='incident_journal_entries')
    note = models.TextField()
    risk_level = models.CharField(max_length=20, choices=RISK_LEVEL_CHOICES, default='medium')
    tags = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Journal #{self.id} for incident {self.incident_id}"
