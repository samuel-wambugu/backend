from unittest.mock import MagicMock, patch
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from alerts.models import Alert
from voice_recognition.models import VoiceRecording
from voice_recognition.services import VoiceRecognitionService


class VoiceEmergencyFlowTests(TestCase):
    def test_process_recording_creates_alert_and_enqueues_with_alert_id(self):
        user = User.objects.create_user(username='victim', password='StrongPass123!')
        recording = VoiceRecording.objects.create(
            user=user,
            audio_file=SimpleUploadedFile('sample.wav', b'fake-audio', content_type='audio/wav'),
            language='en',
            location={'lat': 1.0, 'lng': 2.0},
        )

        with patch('voice_recognition.services._get_whisper_model', return_value=MagicMock()), patch.object(
            VoiceRecognitionService,
            'transcribe_audio',
            return_value={'text': 'help me now', 'segments': [], 'confidence': 91.0},
        ), patch.object(
            VoiceRecognitionService,
            'detect_emergency_keywords',
            return_value={'is_emergency': True, 'detected_keywords': [{'keyword': 'help', 'severity': 4}], 'max_severity': 4},
        ), patch('alerts.services.AlertService.send_emergency_alert') as mock_send:
            service = VoiceRecognitionService()
            result = service.process_recording(recording.id)

        self.assertTrue(result)
        alert = Alert.objects.get(voice_recording=recording)
        self.assertEqual(alert.alert_type, 'voice')
        mock_send.assert_called_once_with(alert.id)
