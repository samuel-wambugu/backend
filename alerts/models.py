from django.db import models
from django.contrib.auth.models import User


class EmergencyContact(models.Model):
    """Emergency contacts for users."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='emergency_contacts')
    name = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    relationship = models.CharField(max_length=50)
    is_primary = models.BooleanField(default=False)
    is_trusted_circle = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-is_primary', 'name']

    def __str__(self):
        return f"{self.name} - {self.user.username}"


class Alert(models.Model):
    """Alert/notification model."""
    ALERT_TYPES = (
        ('voice', 'Voice Emergency'),
        ('sensor', 'Sensor Triggered'),
        ('manual', 'Manual Activation'),
        ('location', 'Unsafe Location'),
        ('checkin_missed', 'Missed Safe Check-In'),
        ('live_session_missed', 'Missed Live Safety Session'),
    )
    
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='alerts')
    alert_type = models.CharField(max_length=20, choices=ALERT_TYPES)
    message = models.TextField()
    location = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    priority = models.IntegerField(default=1)  # 1-5
    
    # Notification channels
    sms_sent = models.BooleanField(default=False)
    push_sent = models.BooleanField(default=False)
    email_sent = models.BooleanField(default=False)
    
    # Related records
    voice_recording = models.ForeignKey(
        'voice_recognition.VoiceRecording',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    sensor_reading = models.ForeignKey(
        'sensors.SensorReading',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.alert_type} - {self.user.username} - {self.created_at}"


class AlertLog(models.Model):
    """Log of alert delivery attempts."""
    alert = models.ForeignKey(Alert, on_delete=models.CASCADE, related_name='logs')
    contact = models.ForeignKey(EmergencyContact, on_delete=models.SET_NULL, null=True)
    channel = models.CharField(max_length=20)  # SMS, Push, Email
    status = models.CharField(max_length=20)
    response = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.alert.id} - {self.channel} - {self.status}"


class SafeCheckIn(models.Model):
    """Scheduled user safety check-in with escalation when missed."""

    STATUS_CHOICES = (
        ('scheduled', 'Scheduled'),
        ('completed', 'Completed'),
        ('missed', 'Missed'),
        ('cancelled', 'Cancelled'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='safe_checkins')
    title = models.CharField(max_length=120)
    note = models.TextField(blank=True)
    scheduled_for = models.DateTimeField()
    grace_minutes = models.PositiveIntegerField(default=10)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    location_snapshot = models.JSONField(null=True, blank=True)
    destination = models.CharField(max_length=255, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    missed_at = models.DateTimeField(null=True, blank=True)
    escalated_alert = models.ForeignKey(
        Alert,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='originating_checkins',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-scheduled_for', '-created_at']

    def __str__(self):
        return f"Check-in {self.user.username} at {self.scheduled_for} ({self.status})"


class LiveSafetySession(models.Model):
    """Active safety session that requires periodic user pings."""

    STATUS_CHOICES = (
        ('active', 'Active'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('escalated', 'Escalated'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='live_safety_sessions')
    title = models.CharField(max_length=120)
    note = models.TextField(blank=True)
    destination = models.CharField(max_length=255, blank=True)
    check_in_interval_minutes = models.PositiveIntegerField(default=15)
    started_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_ping_at = models.DateTimeField(null=True, blank=True)
    current_location = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    completed_at = models.DateTimeField(null=True, blank=True)
    escalated_alert = models.ForeignKey(
        Alert,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='originating_live_sessions',
    )
    trusted_contacts = models.ManyToManyField(EmergencyContact, blank=True, related_name='live_sessions')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-started_at', '-updated_at']

    def __str__(self):
        return f"Live session {self.user.username}: {self.title} ({self.status})"
