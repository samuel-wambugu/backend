from rest_framework import serializers
from .models import (
    AIAuditRecord,
    AIFullAccessGrant,
    AIOwnerInboxMessage,
    AIOwnerInboxThread,
)


class IncidentAnalysisRequestSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(max_length=5000)
    transcription = serializers.CharField(required=False, allow_blank=True)
    location = serializers.JSONField(required=False)
    dry_run = serializers.BooleanField(required=False)
    provider = serializers.CharField(required=False, allow_blank=True)


class ProviderStatusSerializer(serializers.Serializer):
    active_provider = serializers.CharField(allow_blank=True)
    providers = serializers.ListField(child=serializers.DictField())


class IncidentTriageRequestSerializer(serializers.Serializer):
    incident_id = serializers.IntegerField()
    dry_run = serializers.BooleanField(required=False)
    provider = serializers.CharField(required=False, allow_blank=True)
    sensor_limit = serializers.IntegerField(min_value=1, max_value=20, default=5)


class SafetyTipsChatRequestSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=2000)
    location = serializers.JSONField(required=False)
    language = serializers.ChoiceField(choices=['en', 'sw'], required=False, default='en')


class OwnerAssistanceRequestSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=2000)
    conversation_summary = serializers.CharField(required=False, allow_blank=True, max_length=5000)


class OwnerInboxMessageCreateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=5000)


class OwnerInboxThreadManageSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=['open', 'closed'],
        required=False,
    )
    assigned_owner_user_id = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class OwnerInboxMessageSerializer(serializers.ModelSerializer):
    sender_username = serializers.CharField(source='sender.username', read_only=True)

    class Meta:
        model = AIOwnerInboxMessage
        fields = ['id', 'sender', 'sender_username', 'sender_role', 'body', 'created_at']
        read_only_fields = ['sender', 'sender_username', 'sender_role', 'created_at']


class OwnerInboxThreadSerializer(serializers.ModelSerializer):
    requester_username = serializers.CharField(source='requester.username', read_only=True)
    assigned_owner_username = serializers.CharField(source='assigned_owner.username', read_only=True)
    latest_message_preview = serializers.SerializerMethodField()
    latest_sender_role = serializers.SerializerMethodField()
    message_count = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    def get_latest_message_preview(self, obj):
        latest = obj.messages.order_by('-created_at').first()
        if not latest:
            return ''
        return latest.body[:140]

    def get_latest_sender_role(self, obj):
        latest = obj.messages.order_by('-created_at').first()
        return latest.sender_role if latest else ''

    def get_message_count(self, obj):
        return obj.messages.count()

    def get_unread_count(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        if not user or not getattr(user, 'is_authenticated', False):
            return 0

        is_owner = bool(self.context.get('is_owner_user', False))
        sender_role = 'owner' if is_owner else 'user'
        cutoff = obj.owner_last_read_at if is_owner else obj.requester_last_read_at

        unread_qs = obj.messages.exclude(sender_role=sender_role)
        if cutoff is not None:
            unread_qs = unread_qs.filter(created_at__gt=cutoff)
        return unread_qs.count()

    class Meta:
        model = AIOwnerInboxThread
        fields = [
            'id',
            'requester',
            'requester_username',
            'assigned_owner',
            'assigned_owner_username',
            'subject',
            'status',
            'last_message_at',
            'latest_message_preview',
            'latest_sender_role',
            'message_count',
            'unread_count',
            'created_at',
            'updated_at',
        ]


class OwnerInboxThreadDetailSerializer(OwnerInboxThreadSerializer):
    messages = OwnerInboxMessageSerializer(many=True, read_only=True)
    available_owner_options = serializers.SerializerMethodField()

    def get_available_owner_options(self, obj):
        owners = self.context.get('available_owner_options', [])
        return [
            {
                'id': owner.id,
                'username': owner.username,
            }
            for owner in owners
        ]

    class Meta(OwnerInboxThreadSerializer.Meta):
        fields = OwnerInboxThreadSerializer.Meta.fields + ['messages', 'available_owner_options']


class AIAuditRecordSerializer(serializers.ModelSerializer):
    incident_id = serializers.IntegerField(source='incident.id', read_only=True)
    urgency = serializers.SerializerMethodField()
    risk_score = serializers.SerializerMethodField()
    recommended_actions = serializers.SerializerMethodField()
    explanation_summary = serializers.SerializerMethodField()
    risk_indicators = serializers.SerializerMethodField()
    confidence_label = serializers.SerializerMethodField()

    def get_urgency(self, obj):
        return (obj.response_payload or {}).get('urgency')

    def get_risk_score(self, obj):
        return (obj.response_payload or {}).get('risk_score')

    def get_recommended_actions(self, obj):
        return (obj.response_payload or {}).get('recommended_actions', [])

    def get_explanation_summary(self, obj):
        return (obj.response_payload or {}).get('explanation_summary', '')

    def get_risk_indicators(self, obj):
        return (obj.response_payload or {}).get('risk_indicators', [])

    def get_confidence_label(self, obj):
        return (obj.response_payload or {}).get('confidence_label', 'limited-signal')

    class Meta:
        model = AIAuditRecord
        fields = [
            'id', 'incident_id', 'provider', 'model_name', 'endpoint_name', 'dry_run',
            'success', 'latency_ms', 'status_code', 'moderation_flags',
            'request_metadata', 'external_request_id', 'error_message',
            'urgency', 'risk_score', 'recommended_actions', 'explanation_summary',
            'risk_indicators', 'confidence_label', 'created_at'
        ]


class AIFullAccessGrantUpsertSerializer(serializers.Serializer):
    grantee_user_id = serializers.IntegerField(min_value=1)
    can_use_all_features = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)
    note = serializers.CharField(required=False, allow_blank=True, max_length=255)


class AIFullAccessGrantSerializer(serializers.ModelSerializer):
    owner_user_id = serializers.IntegerField(source='owner.id', read_only=True)
    owner_username = serializers.CharField(source='owner.username', read_only=True)
    grantee_user_id = serializers.IntegerField(source='grantee.id', read_only=True)
    grantee_username = serializers.CharField(source='grantee.username', read_only=True)

    class Meta:
        model = AIFullAccessGrant
        fields = [
            'id', 'owner_user_id', 'owner_username',
            'grantee_user_id', 'grantee_username',
            'can_use_all_features', 'is_active', 'note',
            'granted_at', 'updated_at',
        ]
