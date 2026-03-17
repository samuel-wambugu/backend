from django.db import models
from django.contrib.auth.models import User


class UserProfile(models.Model):
    """Extended user profile."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone_number = models.CharField(max_length=20, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    address = models.TextField(blank=True)
    emergency_mode = models.BooleanField(default=False)
    fcm_token = models.CharField(max_length=255, blank=True)  # For push notifications
    location_sharing_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Profile - {self.user.username}"


class SafeLocation(models.Model):
    """User's safe locations."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='safe_locations')
    name = models.CharField(max_length=100)
    address = models.TextField()
    latitude = models.FloatField()
    longitude = models.FloatField()
    radius = models.FloatField(default=100)  # meters
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.name} - {self.user.username}"


class EmailVerificationOTP(models.Model):
    """One-time passcode used in authentication flows."""

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='email_verification_otps',
    )
    purpose = models.CharField(max_length=32, default='login')
    code = models.CharField(max_length=6)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at']),
            models.Index(fields=['user', 'purpose', 'created_at']),
            models.Index(fields=['expires_at']),
        ]

    def __str__(self):
        return f"Email OTP for {self.user.username} at {self.created_at}"
