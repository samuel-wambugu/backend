from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from typing import Any, cast
import logging
from django.utils import timezone
from django.db.models import Q
from django.conf import settings
from .models import Alert, EmergencyContact, AlertLog, SafeCheckIn, LiveSafetySession
from .serializers import (
    AlertSerializer, EmergencyContactSerializer,
    AlertLogSerializer, ManualAlertSerializer,
    SafeCheckInSerializer, SafeCheckInCreateSerializer,
    SafeCheckInActionSerializer,
    LiveSafetySessionSerializer, LiveSafetySessionCreateSerializer,
    LiveSafetySessionActionSerializer,
    LiveSafetySessionTrustedCircleSerializer,
    LiveSafetySessionTrustedCircleNotifySerializer,
)
from .tasks import send_emergency_alert, evaluate_safe_checkin, evaluate_live_session
from .services import AlertService


logger = logging.getLogger(__name__)


def _dispatch_emergency_alert(alert_id: int) -> None:
    """Dispatch emergency alert task with a debug-safe synchronous path."""
    dispatch_mode = getattr(settings, 'ALERT_DISPATCH_MODE', '').strip().lower()
    if not dispatch_mode:
        dispatch_mode = 'sync' if settings.DEBUG else 'async'

    if dispatch_mode == 'sync':
        # Local/dev default: do not depend on separate Celery worker process.
        result = cast(Any, send_emergency_alert).apply(args=[alert_id], throw=False)
        return result.result if hasattr(result, 'result') else None

    try:
        cast(Any, send_emergency_alert).delay(alert_id)
    except Exception as exc:
        logger.exception(
            'emergency_alert_async_dispatch_failed',
            extra={'alert_id': alert_id, 'error': str(exc)},
        )
        # Keep API responsive in local/dev when Celery broker is down.
        result = cast(Any, send_emergency_alert).apply(args=[alert_id], throw=False)
        return result.result if hasattr(result, 'result') else None

    return None


class AlertViewSet(viewsets.ModelViewSet):
    """ViewSet for alerts."""
    queryset = Alert.objects.all()
    serializer_class = AlertSerializer
    
    def get_queryset(self):
        """Filter alerts by current user."""
        return self.queryset.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        """Create alert and trigger sending."""
        alert = serializer.save(user=self.request.user)
        _dispatch_emergency_alert(alert.id)
    
    @action(detail=False, methods=['post'])
    def manual(self, request):
        """Manually trigger an emergency alert."""
        serializer = ManualAlertSerializer(data=request.data)
        
        if serializer.is_valid():
            alert = Alert.objects.create(
                user=request.user,
                alert_type='manual',
                message=serializer.validated_data['message'],
                location=serializer.validated_data.get('location'),
                priority=serializer.validated_data['priority']
            )
            
            # Send alert asynchronously
            task_result = _dispatch_emergency_alert(alert.id)

            # In sync mode we can immediately determine if nothing was delivered.
            alert.refresh_from_db()
            if alert.status == 'failed' or not (alert.sms_sent or alert.email_sent or alert.push_sent):
                return Response({
                    'status': 'alert_failed',
                    'alert_id': alert.id,
                    'message': 'Emergency alert could not be delivered to any contact. Check delivery status and channel configuration.',
                    'task_result': task_result,
                }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
            return Response({
                'status': 'alert_sent',
                'alert_id': alert.id,
                'message': 'Emergency alert is being sent to your contacts'
            }, status=status.HTTP_201_CREATED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'])
    def recent(self, request):
        """Get recent alerts."""
        alerts = self.get_queryset().order_by('-created_at')[:10]
        serializer = self.get_serializer(alerts, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def delivery_status(self, request, pk=None):
        """Return per-channel delivery summary for one alert."""
        alert = self.get_object()
        logs = AlertLog.objects.filter(alert=alert).order_by('-created_at')

        channel_summary = {}
        for log in logs:
            summary = channel_summary.setdefault(
                log.channel,
                {
                    'sent': 0,
                    'failed': 0,
                    'last_status': log.status,
                    'last_response': log.response,
                    'last_created_at': log.created_at,
                },
            )
            if log.status == 'sent':
                summary['sent'] += 1
            else:
                summary['failed'] += 1

        return Response(
            {
                'alert_id': alert.id,
                'alert_type': alert.alert_type,
                'alert_status': alert.status,
                'created_at': alert.created_at,
                'channels': channel_summary,
                'total_logs': logs.count(),
            }
        )

    @action(detail=True, methods=['post'])
    def retry_failed_channels(self, request, pk=None):
        """Retry failed contact-level channels for one alert."""
        alert = self.get_object()
        failed_logs = (
            AlertLog.objects
            .filter(alert=alert, status='failed', contact__isnull=False)
            .order_by('-created_at')
        )

        if not failed_logs.exists():
            return Response(
                {
                    'alert_id': alert.id,
                    'retried': 0,
                    'succeeded': 0,
                    'failed': 0,
                    'details': [],
                    'message': 'No failed contact channels to retry.',
                }
            )

        service = AlertService()
        details = []
        retried = 0
        succeeded = 0
        failed_count = 0

        latest_by_key = {}
        for log in failed_logs:
            key = (log.contact_id, log.channel)
            if key not in latest_by_key:
                latest_by_key[key] = log

        for log in latest_by_key.values():
            contact = log.contact
            if contact is None:
                continue

            result = {'success': False, 'error': 'Unsupported channel'}
            channel = log.channel
            retried += 1

            if channel == 'SMS':
                result = service.send_sms_alert(contact.phone_number, alert.message, alert.id)
            elif channel == 'VoiceCall':
                result = service.send_voice_call_alert(contact.phone_number, alert.message, alert.id)
            elif channel == 'Email' and contact.email:
                subject = 'Emergency Alert (Retry)'
                result = service.send_email_alert(contact.email, subject, alert.message)

            retry_status = 'sent' if result.get('success') else 'failed'
            if retry_status == 'sent':
                succeeded += 1
            else:
                failed_count += 1

            AlertLog.objects.create(
                alert=alert,
                contact=contact,
                channel=channel,
                status=retry_status,
                response=f"retry: {result}",
            )

            details.append(
                {
                    'channel': channel,
                    'contact': contact.name,
                    'status': retry_status,
                    'result': result,
                }
            )

        return Response(
            {
                'alert_id': alert.id,
                'retried': retried,
                'succeeded': succeeded,
                'failed': failed_count,
                'details': details,
            }
        )


class EmergencyContactViewSet(viewsets.ModelViewSet):
    """ViewSet for emergency contacts."""
    queryset = EmergencyContact.objects.all()
    serializer_class = EmergencyContactSerializer
    
    def get_queryset(self):
        """Filter contacts by current user (active-only by default)."""
        queryset = self.queryset.filter(user=self.request.user)
        include_inactive = str(self.request.query_params.get('include_inactive', '')).lower() in {
            '1', 'true', 'yes'
        }
        if not include_inactive:
            queryset = queryset.filter(is_active=True)
        return queryset
    
    def perform_create(self, serializer):
        """Create emergency contact for current user."""
        contact = serializer.save(user=self.request.user)
        if getattr(serializer, 'matched_user_exists', False):
            self._notify_enlisted_contact(contact, self.request.user)
        else:
            self._notify_pending_invite(contact, self.request.user)

    def perform_update(self, serializer):
        """Update contact and notify when enlistment identity changes."""
        notify_fields = {'name', 'phone_number', 'email', 'relationship'}
        should_notify = any(field in serializer.validated_data for field in notify_fields)

        # If owner edits key identity fields without explicitly setting is_active,
        # treat this as re-confirmation and re-activate the contact.
        if should_notify and 'is_active' not in serializer.validated_data:
            serializer.validated_data['is_active'] = True

        contact = serializer.save()
        if should_notify:
            if getattr(serializer, 'matched_user_exists', False):
                self._notify_enlisted_contact(contact, self.request.user)
            else:
                self._notify_pending_invite(contact, self.request.user)

    def _notify_enlisted_contact(self, contact, owner_user):
        service = AlertService()
        sms_message = (
            f"You have been enlisted as an emergency contact by {owner_user.username} in GBV Safety App. "
            "If you prefer to opt out, open the app and remove yourself from emergency contact lists in settings."
        )
        service.send_sms_alert(contact.phone_number, sms_message)

        if contact.email:
            service.send_email_alert(
                contact.email,
                'You were added as an emergency contact',
                (
                    f'Hello {contact.name},\n\n'
                    f'{owner_user.username} added you as an emergency contact in GBV Safety App.\n'
                    'If you do not want to stay on this list, log in and remove yourself from emergency contact lists.\n\n'
                    'GBV Safety App'
                ),
            )

    def _notify_pending_invite(self, contact, owner_user):
        service = AlertService()
        invite_link = getattr(settings, 'APP_REGISTER_URL', 'http://localhost:3000/register')
        sms_message = (
            f"{owner_user.username} added you as an emergency contact in GBV Safety App. "
            f"Please create your account to activate this link: {invite_link}"
        )
        service.send_sms_alert(contact.phone_number, sms_message)

        if contact.email:
            service.send_email_alert(
                contact.email,
                'Invitation to join GBV Safety App',
                (
                    f'Hello {contact.name},\n\n'
                    f'{owner_user.username} added you as an emergency contact in GBV Safety App.\n'
                    f'Create your account here to activate emergency contact support: {invite_link}\n\n'
                    'GBV Safety App'
                ),
            )
    
    @action(detail=True, methods=['post'])
    def set_primary(self, request, pk=None):
        """Set a contact as primary."""
        contact = self.get_object()
        
        # Remove primary from all other contacts
        EmergencyContact.objects.filter(
            user=request.user,
            is_primary=True
        ).update(is_primary=False)
        
        # Set this contact as primary
        contact.is_primary = True
        contact.save()
        
        return Response({
            'status': 'success',
            'message': f'{contact.name} is now the primary contact'
        })

    @action(detail=False, methods=['post'])
    def notify_trusted_circle(self, request):
        """Send one message to all active trusted-circle contacts."""
        message = (request.data.get('message') or '').strip()
        contacts = EmergencyContact.objects.filter(
            user=request.user,
            is_trusted_circle=True,
            is_active=True,
        )
        if not contacts.exists():
            return Response(
                {'detail': 'No trusted-circle contacts configured.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not message:
            message = f"Safety update from {request.user.username}. Please check in with me as soon as possible."

        service = AlertService()
        sent = 0
        failed = 0
        for contact in contacts:
            result = service.send_sms_alert(contact.phone_number, message)
            if result.get('success'):
                sent += 1
            else:
                failed += 1

        return Response({'sent': sent, 'failed': failed})

    @action(detail=False, methods=['post'])
    def clear_trusted_circle(self, request):
        """Remove all contacts from trusted-circle list for current user."""
        updated = EmergencyContact.objects.filter(
            user=request.user,
            is_trusted_circle=True,
        ).update(is_trusted_circle=False)
        return Response({'cleared': updated})

    @action(detail=False, methods=['post'])
    def remove_self(self, request):
        """Allow a user to remove themselves from other users' emergency contacts."""
        email = (request.user.email or '').strip()
        phone = ''
        profile = getattr(request.user, 'profile', None)
        if profile:
            phone = (profile.phone_number or '').strip()

        if not email and not phone:
            return Response(
                {
                    'removed': 0,
                    'detail': 'No email or phone number on your profile to match emergency contacts.',
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        matcher = Q()
        if email:
            matcher |= Q(email__iexact=email)
        if phone:
            matcher |= Q(phone_number=phone)

        queryset = EmergencyContact.objects.filter(matcher).exclude(user=request.user)
        removed = queryset.count()
        queryset.delete()
        return Response({'removed': removed})


class SafeCheckInViewSet(viewsets.ModelViewSet):
    queryset = SafeCheckIn.objects.all()

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.action == 'create':
            return SafeCheckInCreateSerializer
        if self.action in {'complete', 'cancel'}:
            return SafeCheckInActionSerializer
        return SafeCheckInSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        checkin = serializer.save(user=request.user)

        due_at = checkin.scheduled_for + timezone.timedelta(minutes=checkin.grace_minutes)
        countdown = max(int((due_at - timezone.now()).total_seconds()), 1)
        cast(Any, evaluate_safe_checkin).apply_async(args=[checkin.id], countdown=countdown)

        response_serializer = SafeCheckInSerializer(checkin)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        checkin = self.get_object()
        if checkin.status != 'scheduled':
            return Response({'detail': 'Only scheduled check-ins can be completed.'}, status=status.HTTP_400_BAD_REQUEST)

        note = serializer.validated_data.get('note', '').strip()
        if note:
            checkin.note = f"{checkin.note}\nCompletion note: {note}".strip()
        checkin.status = 'completed'
        checkin.completed_at = timezone.now()
        checkin.save(update_fields=['note', 'status', 'completed_at', 'updated_at'])
        return Response(SafeCheckInSerializer(checkin).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        checkin = self.get_object()
        if checkin.status != 'scheduled':
            return Response({'detail': 'Only scheduled check-ins can be cancelled.'}, status=status.HTTP_400_BAD_REQUEST)

        note = serializer.validated_data.get('note', '').strip()
        if note:
            checkin.note = f"{checkin.note}\nCancellation note: {note}".strip()
        checkin.status = 'cancelled'
        checkin.save(update_fields=['note', 'status', 'updated_at'])
        return Response(SafeCheckInSerializer(checkin).data)


class LiveSafetySessionViewSet(viewsets.ModelViewSet):
    queryset = LiveSafetySession.objects.all()

    def get_queryset(self):
        return self.queryset.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.action == 'create':
            return LiveSafetySessionCreateSerializer
        if self.action in {'ping', 'complete', 'cancel'}:
            return LiveSafetySessionActionSerializer
        return LiveSafetySessionSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        trusted_contact_ids = serializer.validated_data.pop('trusted_contact_ids', [])
        live_session = serializer.save(user=request.user, last_ping_at=timezone.now())

        if trusted_contact_ids:
            trusted_contacts = EmergencyContact.objects.filter(
                user=request.user,
                id__in=trusted_contact_ids,
                is_active=True,
            )
            live_session.trusted_contacts.set(trusted_contacts)

        cast(Any, evaluate_live_session).apply_async(
            args=[live_session.id],
            countdown=max(live_session.check_in_interval_minutes * 60, 1),
        )

        response_serializer = LiveSafetySessionSerializer(live_session)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def ping(self, request, pk=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        live_session = self.get_object()
        if live_session.status != 'active':
            return Response({'detail': 'Only active sessions can be updated.'}, status=status.HTTP_400_BAD_REQUEST)

        note = serializer.validated_data.get('note', '').strip()
        if note:
            live_session.note = f"{live_session.note}\nPing note: {note}".strip()
        if 'location' in serializer.validated_data:
            live_session.current_location = serializer.validated_data['location']
        live_session.last_ping_at = timezone.now()
        live_session.save(update_fields=['note', 'current_location', 'last_ping_at', 'updated_at'])
        cast(Any, evaluate_live_session).apply_async(
            args=[live_session.id],
            countdown=max(live_session.check_in_interval_minutes * 60, 1),
        )
        return Response(LiveSafetySessionSerializer(live_session).data)

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        live_session = self.get_object()
        if live_session.status != 'active':
            return Response({'detail': 'Only active sessions can be completed.'}, status=status.HTTP_400_BAD_REQUEST)

        note = serializer.validated_data.get('note', '').strip()
        if note:
            live_session.note = f"{live_session.note}\nCompletion note: {note}".strip()
        live_session.status = 'completed'
        live_session.completed_at = timezone.now()
        live_session.save(update_fields=['note', 'status', 'completed_at', 'updated_at'])
        return Response(LiveSafetySessionSerializer(live_session).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        live_session = self.get_object()
        if live_session.status != 'active':
            return Response({'detail': 'Only active sessions can be cancelled.'}, status=status.HTTP_400_BAD_REQUEST)

        note = serializer.validated_data.get('note', '').strip()
        if note:
            live_session.note = f"{live_session.note}\nCancellation note: {note}".strip()
        live_session.status = 'cancelled'
        live_session.save(update_fields=['note', 'status', 'updated_at'])
        return Response(LiveSafetySessionSerializer(live_session).data)

    @action(detail=True, methods=['post'])
    def set_trusted_circle(self, request, pk=None):
        serializer = LiveSafetySessionTrustedCircleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        live_session = self.get_object()

        contact_ids = serializer.validated_data.get('contact_ids', [])
        contacts = EmergencyContact.objects.filter(
            user=request.user,
            id__in=contact_ids,
            is_active=True,
        )
        if len(contact_ids) != contacts.count():
            return Response(
                {'detail': 'Some selected contacts are invalid or inactive.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        live_session.trusted_contacts.set(contacts)
        return Response(LiveSafetySessionSerializer(live_session).data)

    @action(detail=True, methods=['post'])
    def notify_trusted_circle(self, request, pk=None):
        serializer = LiveSafetySessionTrustedCircleNotifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        live_session = self.get_object()

        contacts = live_session.trusted_contacts.filter(is_active=True)
        if not contacts.exists():
            return Response(
                {'detail': 'No trusted-circle contacts assigned to this session.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        default_message = (
            f"Safety update from {request.user.username}: "
            f"Live session '{live_session.title}' is active."
        )
        message = serializer.validated_data.get('message', '').strip() or default_message
        service = AlertService()
        sent = 0
        failed = 0
        for contact in contacts:
            result = service.send_sms_alert(contact.phone_number, message)
            if result.get('success'):
                sent += 1
            else:
                failed += 1

        return Response({'sent': sent, 'failed': failed})
