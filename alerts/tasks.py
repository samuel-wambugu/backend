from celery import shared_task
import logging
from typing import Any, cast
from django.utils import timezone
from .services import AlertService
from .models import SafeCheckIn, LiveSafetySession


logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 3})
def send_emergency_alert(self, alert_id):
    """
    Celery task to send emergency alert asynchronously.
    
    Args:
        alert_id: ID of Alert instance
        
    Returns:
        dict: Alert sending results
    """
    service = AlertService()
    results = service.send_emergency_alert(alert_id)

    if isinstance(results, dict) and results.get('error'):
        raise RuntimeError(f"Emergency alert dispatch failed: {results['error']}")

    logger.info("emergency_alert_dispatched", extra={'alert_id': alert_id})
    
    return {
        'alert_id': alert_id,
        'results': results
    }


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 3})
def send_sms_task(self, phone_number, message, alert_id=None):
    """
    Celery task to send SMS.
    """
    service = AlertService()
    return service.send_sms_alert(phone_number, message, alert_id)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 3})
def send_push_task(self, device_token, title, body, data=None):
    """
    Celery task to send push notification.
    """
    service = AlertService()
    return service.send_push_notification(device_token, title, body, data)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 3})
def evaluate_safe_checkin(self, checkin_id):
    """Escalate a scheduled check-in if it was not completed in time."""
    checkin = SafeCheckIn.objects.select_related('user', 'escalated_alert').get(id=checkin_id)
    if checkin.status != 'scheduled':
        return {'checkin_id': checkin_id, 'status': checkin.status, 'escalated': False}

    due_at = checkin.scheduled_for + timezone.timedelta(minutes=checkin.grace_minutes)
    now = timezone.now()
    if now < due_at:
        remaining_seconds = max(int((due_at - now).total_seconds()), 1)
        cast(Any, evaluate_safe_checkin).apply_async(args=[checkin_id], countdown=remaining_seconds)
        return {'checkin_id': checkin_id, 'status': 'scheduled', 'rescheduled': True}

    service = AlertService()
    alert = service.create_checkin_escalation_alert(checkin)
    checkin.status = 'missed'
    checkin.missed_at = now
    checkin.escalated_alert = alert
    checkin.save(update_fields=['status', 'missed_at', 'escalated_alert', 'updated_at'])
    cast(Any, send_emergency_alert).delay(alert.id)

    logger.info('safe_checkin_missed_escalated', extra={'checkin_id': checkin_id, 'alert_id': alert.id})
    return {'checkin_id': checkin_id, 'status': 'missed', 'escalated': True, 'alert_id': alert.id}


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 3})
def evaluate_live_session(self, live_session_id):
    """Escalate a live session when the user misses a required ping."""
    live_session = LiveSafetySession.objects.select_related('user', 'escalated_alert').get(id=live_session_id)
    if live_session.status != 'active':
        return {'live_session_id': live_session_id, 'status': live_session.status, 'escalated': False}

    now = timezone.now()
    last_ping_at = live_session.last_ping_at or live_session.started_at
    due_at = min(
        last_ping_at + timezone.timedelta(minutes=live_session.check_in_interval_minutes),
        live_session.expires_at,
    )

    if now < due_at:
        remaining_seconds = max(int((due_at - now).total_seconds()), 1)
        cast(Any, evaluate_live_session).apply_async(args=[live_session_id], countdown=remaining_seconds)
        return {'live_session_id': live_session_id, 'status': 'active', 'rescheduled': True}

    service = AlertService()
    alert = service.create_live_session_escalation_alert(live_session)
    live_session.status = 'escalated'
    live_session.escalated_alert = alert
    live_session.save(update_fields=['status', 'escalated_alert', 'updated_at'])

    trusted_contacts = live_session.trusted_contacts.filter(is_active=True)
    trusted_message = (
        f"Trusted-circle alert: {live_session.user.username} missed a live safety session check-in. "
        f"Session: {live_session.title}."
    )
    for contact in trusted_contacts:
        service.send_sms_alert(contact.phone_number, trusted_message, alert.id)

    cast(Any, send_emergency_alert).delay(alert.id)

    logger.info('live_session_missed_escalated', extra={'live_session_id': live_session_id, 'alert_id': alert.id})
    return {'live_session_id': live_session_id, 'status': 'escalated', 'escalated': True, 'alert_id': alert.id}
