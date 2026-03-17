from celery import shared_task
import logging
from incidents.models import Incident
from gbv_backend.celery import app as celery_app
from .services import VoiceRecognitionService


logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 3})
def process_voice_recording(self, recording_id):
    """
    Celery task to process voice recording asynchronously.
    
    Args:
        recording_id: ID of VoiceRecording instance
        
    Returns:
        dict: Processing result
    """
    service = VoiceRecognitionService()
    success = service.process_recording(recording_id)

    if not success:
        raise RuntimeError(f"Voice processing failed for recording_id={recording_id}")

    linked_incident_ids = list(
        Incident.objects.filter(voice_recording_id=recording_id).values_list('id', flat=True)
    )
    for incident_id in linked_incident_ids:
        celery_app.send_task(
            'ai_gateway.tasks.triage_incident_task',
            args=[incident_id, True, '', 'voice_recording_processed'],
        )

    logger.info("voice_recording_processed", extra={'recording_id': recording_id})
    
    return {
        'recording_id': recording_id,
        'success': success
    }


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={'max_retries': 3})
def notify_emergency_contacts_of_recording(self, recording_id):
    """
    Immediately notify all active emergency contacts when a voice recording is uploaded.
    Sends SMS and email with the audio file link so contacts can take immediate action.
    """
    from django.conf import settings
    from .models import VoiceRecording
    from alerts.models import EmergencyContact
    from alerts.services import AlertService

    try:
        recording = VoiceRecording.objects.get(id=recording_id)
    except VoiceRecording.DoesNotExist:
        logger.warning('notify_recording_contacts_recording_missing', extra={'recording_id': recording_id})
        return {'recording_id': recording_id, 'notified': 0}

    contacts = EmergencyContact.objects.filter(user=recording.user, is_active=True)
    if not contacts.exists():
        logger.info('notify_recording_contacts_no_contacts', extra={'recording_id': recording_id})
        return {'recording_id': recording_id, 'notified': 0}

    # Build an absolute URL for the audio file
    site_url = getattr(settings, 'SITE_URL', '').rstrip('/')
    audio_url = ''
    if site_url and recording.audio_file:
        audio_url = f"{site_url}{recording.audio_file.url}"

    # Build location text
    loc = recording.location or {}
    address_parts = [
        str(loc.get('address') or loc.get('address_line') or '').strip(),
        str(loc.get('place_name') or loc.get('locality') or '').strip(),
    ]
    address_str = ', '.join(p for p in address_parts if p)
    lat = loc.get('latitude') or loc.get('lat')
    lng = loc.get('longitude') or loc.get('lng')
    maps_url = str(loc.get('map_url') or '').strip()
    if not maps_url and lat is not None and lng is not None:
        maps_url = f'https://www.openstreetmap.org/?mlat={lat}&mlon={lng}&zoom=17'
    if address_str:
        location_text = f' Location: {address_str}.'
    elif maps_url:
        location_text = f' Location map: {maps_url}.'
    elif lat is not None and lng is not None:
        location_text = f' Coordinates: {lat}, {lng}.'
    else:
        location_text = ''

    username = recording.user.username
    created_at = recording.created_at.strftime('%Y-%m-%d %H:%M UTC') if recording.created_at else 'unknown time'
    audio_suffix = f' Listen: {audio_url}' if audio_url else ''

    sms_message = (
        f"EMERGENCY RECORDING: {username} saved a voice recording at {created_at}."
        f"{location_text} Please check on them immediately.{audio_suffix}"
    )

    email_subject = f"Emergency Voice Recording from {username}"
    email_lines = [
        f"An emergency voice recording was saved by {username}.",
        f"Time: {created_at}",
    ]
    if location_text:
        email_lines.append(location_text.strip())
    if maps_url:
        email_lines.append(f"Map: {maps_url}")
    if audio_url:
        email_lines.append(f"Listen to the recording: {audio_url}")
    email_lines += ['', 'Please check on them immediately or contact the authorities if needed.']
    email_body = '\n'.join(email_lines)

    service = AlertService()
    notified = 0
    for contact in contacts:
        if contact.phone_number:
            service.send_sms_alert(contact.phone_number, sms_message)
        if contact.email:
            service.send_email_alert(contact.email, email_subject, email_body)
        notified += 1

    logger.info(
        'emergency_contacts_notified_of_recording',
        extra={'recording_id': recording_id, 'notified': notified},
    )
    return {'recording_id': recording_id, 'notified': notified}
