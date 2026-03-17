from django.contrib import admin
from .models import Alert, EmergencyContact, AlertLog, SafeCheckIn, LiveSafetySession


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ['user', 'alert_type', 'status', 'priority', 'created_at']
    list_filter = ['alert_type', 'status', 'priority']
    search_fields = ['user__username', 'message']
    readonly_fields = ['sms_sent', 'push_sent', 'email_sent']


@admin.register(EmergencyContact)
class EmergencyContactAdmin(admin.ModelAdmin):
    list_display = ['name', 'user', 'phone_number', 'is_primary', 'is_trusted_circle', 'is_active']
    list_filter = ['is_primary', 'is_trusted_circle', 'is_active', 'relationship']
    search_fields = ['name', 'phone_number', 'user__username']


@admin.register(AlertLog)
class AlertLogAdmin(admin.ModelAdmin):
    list_display = ['alert', 'contact', 'channel', 'status', 'created_at']
    list_filter = ['channel', 'status']
    search_fields = ['alert__id', 'contact__name']


@admin.register(SafeCheckIn)
class SafeCheckInAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'scheduled_for', 'status', 'grace_minutes']
    list_filter = ['status', 'scheduled_for']
    search_fields = ['title', 'user__username', 'destination']
    readonly_fields = ['completed_at', 'missed_at', 'created_at', 'updated_at']


@admin.register(LiveSafetySession)
class LiveSafetySessionAdmin(admin.ModelAdmin):
    list_display = ['title', 'user', 'status', 'started_at', 'expires_at', 'check_in_interval_minutes']
    list_filter = ['status', 'started_at', 'expires_at']
    search_fields = ['title', 'user__username', 'destination']
    readonly_fields = ['started_at', 'last_ping_at', 'completed_at', 'updated_at']
    filter_horizontal = ['trusted_contacts']
