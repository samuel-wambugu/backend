from django.utils import timezone
from django.contrib.auth import get_user_model
from rest_framework import serializers
from .models import Alert, EmergencyContact, AlertLog, SafeCheckIn, LiveSafetySession
import logging


logger = logging.getLogger(__name__)


class EmergencyContactSerializer(serializers.ModelSerializer):
    """Serializer for emergency contacts."""

    linked_user_id = serializers.SerializerMethodField(read_only=True)
    is_registered_user = serializers.SerializerMethodField(read_only=True)

    def _resolve_linked_user(self, email, phone_number):
        user_model = get_user_model()
        by_email = user_model.objects.filter(email__iexact=email).first() if email else None
        by_phone = user_model.objects.filter(profile__phone_number=phone_number).first() if phone_number else None

        if by_email and by_phone and by_email.id != by_phone.id:
            # Do not block contact creation; treat it as unmatched so it can be saved as pending.
            logger.warning(
                'emergency_contact_identity_conflict',
                extra={
                    'email_user_id': by_email.id,
                    'phone_user_id': by_phone.id,
                },
            )
            return None

        return by_email or by_phone

    def get_linked_user_id(self, obj):
        matched = self._resolve_linked_user((obj.email or '').strip(), (obj.phone_number or '').strip())
        return matched.id if matched else None

    def get_is_registered_user(self, obj):
        return self.get_linked_user_id(obj) is not None

    def validate(self, attrs):
        email = (attrs.get('email') if 'email' in attrs else getattr(self.instance, 'email', '')) or ''
        phone_number = (
            attrs.get('phone_number')
            if 'phone_number' in attrs
            else getattr(self.instance, 'phone_number', '')
        ) or ''

        email = email.strip()
        phone_number = phone_number.strip()

        if not email and not phone_number:
            raise serializers.ValidationError(
                'Emergency contact must include at least an email or phone number.'
            )

        self._matched_user = self._resolve_linked_user(email, phone_number)
        self.matched_user_exists = self._matched_user is not None

        return attrs
    
    class Meta:
        model = EmergencyContact
        fields = [
            'id', 'name', 'phone_number', 'email',
            'relationship', 'is_primary', 'is_trusted_circle', 'is_active', 'created_at', 'linked_user_id', 'is_registered_user'
        ]


class AlertLogSerializer(serializers.ModelSerializer):
    """Serializer for alert logs."""
    
    class Meta:
        model = AlertLog
        fields = ['id', 'contact', 'channel', 'status', 'response', 'created_at']


class AlertSerializer(serializers.ModelSerializer):
    """Serializer for alerts."""
    logs = AlertLogSerializer(many=True, read_only=True)
    
    class Meta:
        model = Alert
        fields = [
            'id', 'alert_type', 'message', 'location', 'status',
            'priority', 'sms_sent', 'push_sent', 'email_sent',
            'voice_recording', 'sensor_reading', 'created_at',
            'updated_at', 'logs'
        ]
        read_only_fields = ['sms_sent', 'push_sent', 'email_sent', 'status']


class ManualAlertSerializer(serializers.Serializer):
    """Serializer for manually triggering alerts."""
    message = serializers.CharField(max_length=500)
    # location is optional — alerts must still be dispatched when GPS is
    # unavailable (e.g. web browser without permission), but the payload is
    # validated strictly when it IS present.
    location = serializers.JSONField(required=False, allow_null=True)
    priority = serializers.IntegerField(min_value=1, max_value=5, default=5)

    def validate_location(self, value):
        if value is None:
            return value

        if not isinstance(value, dict):
            raise serializers.ValidationError('Location must be a JSON object with latitude and longitude.')

        latitude = value.get('latitude', value.get('lat'))
        longitude = value.get('longitude', value.get('lng'))

        if latitude is None or longitude is None:
            raise serializers.ValidationError('Location must include latitude and longitude.')

        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError):
            raise serializers.ValidationError('Latitude and longitude must be valid numbers.')

        if latitude < -90 or latitude > 90:
            raise serializers.ValidationError('Latitude must be between -90 and 90.')
        if longitude < -180 or longitude > 180:
            raise serializers.ValidationError('Longitude must be between -180 and 180.')

        # Inject canonical map links so contacts always get a clickable URL.
        lat_f = float(latitude)
        lon_f = float(longitude)
        value.setdefault(
            'map_url',
            f'https://www.openstreetmap.org/?mlat={lat_f}&mlon={lon_f}&zoom=17',
        )

        return value


class SafeCheckInSerializer(serializers.ModelSerializer):
    class Meta:
        model = SafeCheckIn
        fields = [
            'id', 'title', 'note', 'scheduled_for', 'grace_minutes',
            'status', 'location_snapshot', 'destination', 'completed_at',
            'missed_at', 'escalated_alert', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'status', 'completed_at', 'missed_at', 'escalated_alert',
            'created_at', 'updated_at'
        ]


class SafeCheckInCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = SafeCheckIn
        fields = ['title', 'note', 'scheduled_for', 'grace_minutes', 'location_snapshot', 'destination']

    def validate_grace_minutes(self, value):
        if value < 1 or value > 60:
            raise serializers.ValidationError('Grace minutes must be between 1 and 60.')
        return value


class SafeCheckInActionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class LiveSafetySessionSerializer(serializers.ModelSerializer):
    trusted_contact_ids = serializers.SerializerMethodField()

    def get_trusted_contact_ids(self, obj):
        return list(obj.trusted_contacts.values_list('id', flat=True))

    class Meta:
        model = LiveSafetySession
        fields = [
            'id', 'title', 'note', 'destination', 'check_in_interval_minutes',
            'started_at', 'expires_at', 'last_ping_at', 'current_location',
            'status', 'completed_at', 'escalated_alert', 'trusted_contact_ids', 'updated_at'
        ]
        read_only_fields = [
            'started_at', 'last_ping_at', 'status', 'completed_at',
            'escalated_alert', 'updated_at'
        ]


class LiveSafetySessionCreateSerializer(serializers.ModelSerializer):
    trusted_contact_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
    )

    class Meta:
        model = LiveSafetySession
        fields = [
            'title',
            'note',
            'destination',
            'check_in_interval_minutes',
            'expires_at',
            'current_location',
            'trusted_contact_ids',
        ]

    def validate_check_in_interval_minutes(self, value):
        if value < 1 or value > 120:
            raise serializers.ValidationError('Check-in interval must be between 1 and 120 minutes.')
        return value

    def validate(self, attrs):
        expires_at = attrs.get('expires_at')
        if expires_at and expires_at <= timezone.now() + timezone.timedelta(minutes=1):
            raise serializers.ValidationError({'expires_at': 'Session must end at least one minute in the future.'})
        return attrs


class LiveSafetySessionActionSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)
    location = serializers.JSONField(required=False)


class LiveSafetySessionTrustedCircleSerializer(serializers.Serializer):
    contact_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        allow_empty=True,
    )


class LiveSafetySessionTrustedCircleNotifySerializer(serializers.Serializer):
    message = serializers.CharField(max_length=500, required=False, allow_blank=True)
