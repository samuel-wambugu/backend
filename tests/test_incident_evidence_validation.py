from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from incidents.serializers import IncidentEvidenceSerializer


@override_settings(MAX_EVIDENCE_FILE_SIZE_MB=1)
class IncidentEvidenceValidationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='reporter', password='StrongPass123!')

    def test_rejects_wrong_extension_for_type(self):
        serializer = IncidentEvidenceSerializer(
            data={
                'evidence_type': 'photo',
                'file': SimpleUploadedFile('voice.mp3', b'123', content_type='audio/mpeg'),
                'description': 'bad extension',
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn('file', serializer.errors)

    def test_rejects_oversized_file(self):
        serializer = IncidentEvidenceSerializer(
            data={
                'evidence_type': 'document',
                'file': SimpleUploadedFile('report.pdf', b'X' * (2 * 1024 * 1024), content_type='application/pdf'),
                'description': 'too big',
            }
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn('file', serializer.errors)

    def test_accepts_valid_file(self):
        serializer = IncidentEvidenceSerializer(
            data={
                'evidence_type': 'audio',
                'file': SimpleUploadedFile('clip.wav', b'123', content_type='audio/wav'),
                'description': 'valid audio',
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
