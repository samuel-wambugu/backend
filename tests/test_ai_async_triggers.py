from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from incidents.models import Incident
from alerts.models import Alert
from sensors.models import SensorAlert, SensorDevice
from sensors.services import SensorService
from voice_recognition.models import VoiceRecording
from voice_recognition.tasks import process_voice_recording


class AIAsyncTriggerTests(TestCase):
    def test_voice_processing_queues_triage_for_linked_incident(self):
        user = User.objects.create_user(username='voice-user', password='StrongPass123!')
        recording = VoiceRecording.objects.create(
            user=user,
            audio_file=SimpleUploadedFile('clip.wav', b'audio', content_type='audio/wav'),
            processed=False,
        )
        incident = Incident.objects.create(
            reporter=user,
            title='Voice evidence incident',
            description='Linked to recording',
            incident_date='2026-03-13T10:00:00Z',
            voice_recording=recording,
        )

        with patch('voice_recognition.tasks.VoiceRecognitionService.process_recording', return_value=True), patch(
            'voice_recognition.tasks.celery_app.send_task'
        ) as mock_send_task:
            result = process_voice_recording.run(recording.id)

        self.assertTrue(result['success'])
        mock_send_task.assert_called_once_with(
            'ai_gateway.tasks.triage_incident_task',
            args=[incident.id, True, '', 'voice_recording_processed'],
        )

    def test_sensor_alert_queues_latest_incident_triage(self):
        user = User.objects.create_user(username='sensor-user', password='StrongPass123!')
        Incident.objects.create(
            reporter=user,
            title='Open incident',
            description='Awaiting triage',
            incident_date='2026-03-13T11:00:00Z',
        )
        device = SensorDevice.objects.create(
            user=user,
            device_id='accelerometer-1',
            sensor_type='accelerometer',
            name='Phone sensor',
            threshold_value=10.0,
        )
        SensorAlert.objects.create(
            device=device,
            condition='greater_than',
            threshold=10.0,
            alert_message='Emergency motion detected',
            priority=5,
        )

        service = SensorService()
        with patch('sensors.services.celery_app.send_task') as mock_send_task:
            result = service.process_sensor_reading(device.device_id, 15.0, location={'lat': 0.1, 'lng': 0.2})

        self.assertTrue(result['success'])
        self.assertTrue(result['alert_triggered'])
        alert = Alert.objects.get(sensor_reading_id=result['reading_id'])
        self.assertEqual(mock_send_task.call_count, 2)
        mock_send_task.assert_any_call('alerts.tasks.send_emergency_alert', args=[alert.id])
        mock_send_task.assert_any_call(
            'ai_gateway.tasks.auto_triage_latest_incident_for_user',
            args=[user.id, True, '', 'sensor_alert'],
        )