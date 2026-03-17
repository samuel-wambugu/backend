import logging

from celery import shared_task
from django.contrib.auth import get_user_model

from incidents.models import Incident

from .services import AIGatewayService


logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 3})
def triage_incident_task(self, incident_id, dry_run=True, provider_name='', trigger='manual'):
    """Run AI triage for a concrete incident asynchronously."""
    service = AIGatewayService()
    incident = Incident.objects.select_related('voice_recording', 'reporter').get(id=incident_id)
    result = service.triage_incident(
        incident,
        dry_run=dry_run,
        provider_name=provider_name,
        user=incident.reporter,
    )
    logger.info(
        'incident_triage_completed',
        extra={'incident_id': incident_id, 'audit_id': result.get('audit_id'), 'trigger': trigger},
    )
    return result


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 3})
def auto_triage_latest_incident_for_user(self, user_id, dry_run=True, provider_name='', trigger='sensor_alert'):
    """Run AI triage for the latest active incident of a user when background signals arrive."""
    user_model = get_user_model()
    user = user_model.objects.get(id=user_id)
    incident = (
        Incident.objects.select_related('voice_recording', 'reporter')
        .filter(reporter=user)
        .exclude(status__in=['resolved', 'closed'])
        .order_by('-created_at')
        .first()
    )

    if incident is None:
        logger.info('incident_triage_skipped_no_active_incident', extra={'user_id': user_id, 'trigger': trigger})
        return {'skipped': True, 'reason': 'no_active_incident'}

    return triage_incident_task.run(
        incident.id,
        dry_run=dry_run,
        provider_name=provider_name,
        trigger=trigger,
    )