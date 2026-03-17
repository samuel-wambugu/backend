from django.conf import settings
from django.db import models


class AIFullAccessGrant(models.Model):
    """Owner-issued permission for enabling full (non-dry-run) AI functionality."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ai_full_access_grants_issued',
    )
    grantee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ai_full_access_grants_received',
    )
    can_use_all_features = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    note = models.CharField(max_length=255, blank=True)
    granted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['owner', 'grantee'], name='unique_owner_grantee_ai_access'),
        ]
        indexes = [
            models.Index(fields=['grantee', 'is_active']),
            models.Index(fields=['owner', 'is_active']),
        ]

    def __str__(self):
        return f"AI access {self.owner_id}->{self.grantee_id} active={self.is_active}"


class AIAuditRecord(models.Model):
    """Persistent record of AI gateway requests and responses."""

    ENDPOINT_CHOICES = (
        ('incident-analysis', 'Incident Analysis'),
        ('incident-triage', 'Incident Triage'),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_audit_records',
    )
    incident = models.ForeignKey(
        'incidents.Incident',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_audit_records',
    )
    voice_recording = models.ForeignKey(
        'voice_recognition.VoiceRecording',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_audit_records',
    )
    provider = models.CharField(max_length=50)
    model_name = models.CharField(max_length=150, blank=True)
    endpoint_name = models.CharField(max_length=30, choices=ENDPOINT_CHOICES)
    dry_run = models.BooleanField(default=True)
    success = models.BooleanField(default=False)
    latency_ms = models.PositiveIntegerField(default=0)
    status_code = models.PositiveIntegerField(null=True, blank=True)
    moderation_flags = models.JSONField(default=dict, blank=True)
    request_metadata = models.JSONField(default=dict, blank=True)
    request_payload = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    external_request_id = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['provider', '-created_at']),
            models.Index(fields=['endpoint_name', '-created_at']),
        ]

    def __str__(self):
        return f"{self.endpoint_name} via {self.provider} at {self.created_at}"


class AIOwnerInboxThread(models.Model):
    STATUS_CHOICES = (
        ('open', 'Open'),
        ('closed', 'Closed'),
    )

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='ai_owner_inbox_threads_requested',
    )
    assigned_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_owner_inbox_threads_assigned',
    )
    subject = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    last_message_at = models.DateTimeField(auto_now_add=True)
    requester_last_read_at = models.DateTimeField(null=True, blank=True)
    owner_last_read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_message_at', '-updated_at']
        indexes = [
            models.Index(fields=['requester', '-last_message_at']),
            models.Index(fields=['assigned_owner', '-last_message_at']),
        ]

    def __str__(self):
        return f"Owner inbox #{self.id} {self.requester_id}->{self.assigned_owner_id}"


class AIOwnerInboxMessage(models.Model):
    SENDER_ROLE_CHOICES = (
        ('user', 'User'),
        ('owner', 'Owner'),
        ('system', 'System'),
    )

    thread = models.ForeignKey(
        AIOwnerInboxThread,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ai_owner_inbox_messages',
    )
    sender_role = models.CharField(max_length=20, choices=SENDER_ROLE_CHOICES)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['thread', 'created_at']),
        ]

    def __str__(self):
        return f"Thread {self.thread_id} message {self.sender_role} at {self.created_at}"