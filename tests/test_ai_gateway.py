import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APITestCase

from ai_gateway.models import AIAuditRecord, AIFullAccessGrant
from ai_gateway.providers import AnthropicProvider, AzureOpenAIProvider, ProviderRequestError
from ai_gateway import services as ai_gateway_services
from alerts.models import Alert
from incidents.models import Incident
from sensors.models import SensorDevice, SensorReading
from voice_recognition.models import VoiceRecording


class ProviderAdapterTests(SimpleTestCase):
    @override_settings(
        AI_AZURE_OPENAI_ENDPOINT='https://example-resource.openai.azure.com',
        AI_AZURE_OPENAI_API_KEY='secret',
        AI_AZURE_OPENAI_DEPLOYMENT='triage-deployment',
        AI_AZURE_OPENAI_API_VERSION='2024-10-21',
    )
    def test_azure_openai_provider_invocation(self):
        provider = AzureOpenAIProvider()
        with patch.object(provider, '_post_json', return_value={
            'status_code': 200,
            'body': {
                'choices': [
                    {'message': {'content': json.dumps({'risk_score': 88, 'urgency': 'critical', 'recommended_actions': ['Call help']})}}
                ]
            },
            'headers': {'x-request-id': 'azure-req-1'},
        }) as mock_post:
            result = provider.invoke([{'role': 'user', 'content': 'incident'}], {'temperature': 0.1})

        self.assertEqual(result['provider'], 'azure-openai')
        self.assertEqual(result['external_request_id'], 'azure-req-1')
        self.assertEqual(result['status_code'], 200)
        mock_post.assert_called_once()

    @override_settings(
        AI_ANTHROPIC_API_KEY='secret',
        AI_ANTHROPIC_MODEL='claude-3-5-sonnet',
        AI_ANTHROPIC_API_BASE_URL='https://api.anthropic.com',
    )
    def test_anthropic_provider_invocation(self):
        provider = AnthropicProvider()
        with patch.object(provider, '_post_json', return_value={
            'status_code': 200,
            'body': {
                'id': 'msg_123',
                'content': [
                    {'type': 'text', 'text': json.dumps({'risk_score': 54, 'urgency': 'high', 'recommended_actions': ['Notify contact']})}
                ],
            },
            'headers': {},
        }) as mock_post:
            result = provider.invoke(
                [
                    {'role': 'system', 'content': 'instructions'},
                    {'role': 'user', 'content': 'incident'},
                ],
                {'temperature': 0.2, 'max_tokens': 100},
            )

        self.assertEqual(result['provider'], 'anthropic')
        self.assertEqual(result['external_request_id'], 'msg_123')
        mock_post.assert_called_once()


class AIGatewayEndpointTests(APITestCase):
    def setUp(self):
        ai_gateway_services._provider_cooldown_state.clear()
        self.owner = User.objects.create_superuser(username='owner-user', email='owner@example.com', password='OwnerPass123!')
        self.user = User.objects.create_user(username='triage-user', password='StrongPass123!')
        self.client.force_authenticate(user=self.user)

    @override_settings(
        AI_PROVIDER='openai',
        AI_OPENAI_API_KEY='secret',
        AI_OPENAI_MODEL='gpt-test',
    )
    @patch('ai_gateway.providers.OpenAIProvider.invoke')
    def test_incident_analysis_uses_provider_and_persists_audit(self, mock_invoke):
        AIFullAccessGrant.objects.create(owner=self.owner, grantee=self.user, can_use_all_features=True, is_active=True)
        mock_invoke.return_value = {
            'provider': 'openai',
            'model_name': 'gpt-test',
            'status_code': 200,
            'raw_response': {'id': 'chatcmpl_test'},
            'text': json.dumps({
                'risk_score': 77,
                'urgency': 'critical',
                'recommended_actions': ['Trigger emergency contacts'],
                'moderation_flags': {'contains_email': False},
            }),
            'external_request_id': 'chatcmpl_test',
        }

        response = self.client.post(
            '/api/ai/incidents/analyze/',
            {
                'title': 'Attacked near bus stop',
                'description': 'There is immediate danger and panic.',
                'transcription': 'help me now',
                'dry_run': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['external_ai_used'])
        audit = AIAuditRecord.objects.get(id=response.data['audit_id'])
        self.assertEqual(audit.provider, 'openai')
        self.assertEqual(audit.model_name, 'gpt-test')
        self.assertTrue(audit.success)
        self.assertEqual(audit.external_request_id, 'chatcmpl_test')

    @override_settings(
        AI_PROVIDER='openai',
        AI_OPENAI_API_KEY='secret',
        AI_OPENAI_MODEL='gpt-test',
    )
    def test_incident_analysis_requires_owner_approval_for_non_dry_run(self):
        response = self.client.post(
            '/api/ai/incidents/analyze/',
            {
                'title': 'Need urgent help',
                'description': 'There is immediate danger nearby.',
                'dry_run': False,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 403)

    @override_settings(
        AI_PROVIDER='openai',
        AI_PROVIDER_FAILOVER_ORDER='azure-openai',
        AI_OPENAI_API_KEY='secret',
        AI_OPENAI_MODEL='gpt-test',
        AI_AZURE_OPENAI_ENDPOINT='https://example-resource.openai.azure.com',
        AI_AZURE_OPENAI_API_KEY='secret',
        AI_AZURE_OPENAI_DEPLOYMENT='triage-deployment',
    )
    @patch('ai_gateway.providers.AzureOpenAIProvider.invoke')
    @patch('ai_gateway.providers.OpenAIProvider.invoke')
    def test_incident_analysis_fails_over_when_primary_rate_limited(self, mock_openai, mock_azure):
        AIFullAccessGrant.objects.create(owner=self.owner, grantee=self.user, can_use_all_features=True, is_active=True)
        mock_openai.side_effect = ProviderRequestError(
            'HTTP Error 429: Too Many Requests',
            status_code=429,
            retryable=True,
        )
        mock_azure.return_value = {
            'provider': 'azure-openai',
            'model_name': 'triage-deployment',
            'status_code': 200,
            'raw_response': {'id': 'azure-ok'},
            'text': json.dumps({
                'risk_score': 64,
                'urgency': 'high',
                'recommended_actions': ['Notify emergency contact'],
                'moderation_flags': {'contains_email': False},
            }),
            'external_request_id': 'azure-ok',
        }

        response = self.client.post(
            '/api/ai/incidents/analyze/',
            {
                'title': 'Escalating risk',
                'description': 'I am being followed and threatened.',
                'dry_run': False,
                'provider': 'openai',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['external_ai_used'])
        self.assertEqual(response.data['provider_attempts'], ['openai', 'azure-openai'])
        audit = AIAuditRecord.objects.get(id=response.data['audit_id'])
        self.assertEqual(audit.provider, 'azure-openai')
        self.assertTrue(audit.success)

    @override_settings(
        AI_PROVIDER='openai',
        AI_PROVIDER_FAILOVER_ORDER='azure-openai,anthropic',
        AI_OPENAI_API_KEY='secret',
        AI_OPENAI_MODEL='gpt-test',
        AI_PROVIDER_SKIP_UNCONFIGURED=True,
    )
    @patch('ai_gateway.providers.OpenAIProvider.invoke')
    def test_failover_skips_unconfigured_providers_without_attempting_them(self, mock_openai):
        AIFullAccessGrant.objects.create(owner=self.owner, grantee=self.user, can_use_all_features=True, is_active=True)
        mock_openai.side_effect = ProviderRequestError(
            'HTTP Error 429: Too Many Requests',
            status_code=429,
            retryable=True,
        )

        response = self.client.post(
            '/api/ai/incidents/analyze/',
            {
                'title': 'Escalating risk',
                'description': 'I am being followed and threatened.',
                'dry_run': False,
                'provider': 'openai',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['external_ai_used'])
        self.assertEqual(response.data['provider_attempts'], ['openai'])
        self.assertEqual(response.data['providers_skipped_unconfigured'], ['azure-openai', 'anthropic'])

    @override_settings(
        AI_PROVIDER='openai',
        AI_PROVIDER_FAILOVER_ORDER='azure-openai',
        AI_OPENAI_API_KEY='secret',
        AI_OPENAI_MODEL='gpt-test',
        AI_PROVIDER_429_COOLDOWN_SECONDS=120,
        AI_AZURE_OPENAI_ENDPOINT='https://example-resource.openai.azure.com',
        AI_AZURE_OPENAI_API_KEY='secret',
        AI_AZURE_OPENAI_DEPLOYMENT='triage-deployment',
    )
    @patch('ai_gateway.providers.AzureOpenAIProvider.invoke')
    @patch('ai_gateway.providers.OpenAIProvider.invoke')
    def test_429_cooldown_bypasses_provider_on_next_request(self, mock_openai, mock_azure):
        AIFullAccessGrant.objects.create(owner=self.owner, grantee=self.user, can_use_all_features=True, is_active=True)
        mock_openai.side_effect = ProviderRequestError(
            'HTTP Error 429: Too Many Requests',
            status_code=429,
            retryable=True,
        )
        mock_azure.return_value = {
            'provider': 'azure-openai',
            'model_name': 'triage-deployment',
            'status_code': 200,
            'raw_response': {'id': 'azure-ok'},
            'text': json.dumps({
                'risk_score': 64,
                'urgency': 'high',
                'recommended_actions': ['Notify emergency contact'],
                'moderation_flags': {'contains_email': False},
            }),
            'external_request_id': 'azure-ok',
        }

        first_response = self.client.post(
            '/api/ai/incidents/analyze/',
            {
                'title': 'Escalating risk first',
                'description': 'I am being followed and threatened.',
                'dry_run': False,
                'provider': 'openai',
            },
            format='json',
        )
        second_response = self.client.post(
            '/api/ai/incidents/analyze/',
            {
                'title': 'Escalating risk second',
                'description': 'I am being followed and threatened again.',
                'dry_run': False,
                'provider': 'openai',
            },
            format='json',
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(mock_openai.call_count, 1)
        self.assertTrue(second_response.data['external_ai_used'])
        self.assertEqual(second_response.data['providers_skipped_cooldown'], ['openai'])
        self.assertEqual(second_response.data['provider_attempts'], ['azure-openai'])

    def test_owner_can_grant_ai_full_access(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            '/api/ai/permissions/grants/',
            {
                'grantee_user_id': self.user.id,
                'can_use_all_features': True,
                'is_active': True,
                'note': 'Approved by owner',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['grantee_user_id'], self.user.id)
        self.assertTrue(response.data['can_use_all_features'])
        self.assertTrue(AIFullAccessGrant.objects.filter(owner=self.owner, grantee=self.user, is_active=True).exists())

    def test_triage_endpoint_combines_incident_voice_and_sensor_context(self):
        voice_recording = VoiceRecording.objects.create(
            user=self.user,
            audio_file=SimpleUploadedFile('voice.wav', b'audio', content_type='audio/wav'),
            transcription='The attacker is following me and I need help now.',
            processed=True,
            location={'lat': 1.5, 'lng': 36.8},
        )
        incident = Incident.objects.create(
            reporter=self.user,
            title='Harassment on the way home',
            description='A person is following and threatening me.',
            incident_date='2026-03-13T10:00:00Z',
            location={'lat': 1.5, 'lng': 36.8},
            severity=4,
            voice_recording=voice_recording,
        )
        sensor = SensorDevice.objects.create(
            user=self.user,
            device_id='sensor-1',
            sensor_type='accelerometer',
            name='Phone accelerometer',
            threshold_value=12.0,
        )
        SensorReading.objects.create(
            device=sensor,
            value=20.0,
            raw_data={'x': 10, 'y': 8, 'z': 7},
            location={'lat': 1.5, 'lng': 36.8},
            is_anomaly=True,
            alert_triggered=True,
        )

        response = self.client.post(
            '/api/ai/incidents/triage/',
            {
                'incident_id': incident.id,
                'dry_run': True,
                'sensor_limit': 5,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['triage_context']['incident_id'], incident.id)
        self.assertEqual(response.data['triage_context']['voice_recording_id'], voice_recording.id)
        self.assertEqual(response.data['triage_context']['sensor_anomaly_count'], 1)
        self.assertEqual(response.data['triage_context']['location'], {'lat': 1.5, 'lng': 36.8})
        audit = AIAuditRecord.objects.get(id=response.data['audit_id'])
        self.assertEqual(audit.endpoint_name, 'incident-triage')
        self.assertEqual(audit.incident_id, incident.id)
        self.assertEqual(audit.voice_recording_id, voice_recording.id)

    def test_audit_endpoint_returns_recent_records(self):
        incident = Incident.objects.create(
            reporter=self.user,
            title='Audit visibility incident',
            description='Testing audit serializer fields',
            incident_date='2026-03-13T10:00:00Z',
        )
        audit = AIAuditRecord.objects.create(
            user=self.user,
            incident=incident,
            provider='fallback',
            model_name='',
            endpoint_name='incident-triage',
            dry_run=True,
            success=True,
            latency_ms=12,
            status_code=200,
            moderation_flags={},
            request_metadata={},
            request_payload={'title': 'test'},
            response_payload={
                'risk_score': 10,
                'urgency': 'medium',
                'recommended_actions': ['Record details'],
            },
        )

        response = self.client.get('/api/ai/audits/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]['id'], audit.id)
        self.assertEqual(response.data[0]['incident_id'], incident.id)
        self.assertEqual(response.data[0]['urgency'], 'medium')
        self.assertEqual(response.data[0]['risk_score'], 10)

    def test_chatbot_tips_endpoint_returns_contextual_safety_guidance(self):
        response = self.client.post(
            '/api/ai/chatbot/tips/',
            {
                'message': 'Someone is following me and threatening me near the market.',
                'location': {'lat': -1.2, 'lng': 36.8},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['location_acknowledged'])
        self.assertTrue(response.data['escalate_to_emergency'])
        self.assertIn('stalking-or-following', response.data['matched_intents'])
        self.assertGreaterEqual(len(response.data['tips']), 1)
        self.assertGreaterEqual(len(response.data['quick_replies']), 1)
        self.assertIn('action_labels', response.data)

    def test_chatbot_tips_endpoint_returns_general_guidance_when_no_match(self):
        response = self.client.post(
            '/api/ai/chatbot/tips/',
            {
                'message': 'Can you give me general safety planning advice?',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('general-safety', response.data['matched_intents'])
        self.assertGreaterEqual(len(response.data['immediate_steps']), 1)

    @override_settings(GBV_HOTLINE_NUMBER='+254119')
    def test_chatbot_tips_endpoint_supports_swahili_language(self):
        response = self.client.post(
            '/api/ai/chatbot/tips/',
            {
                'message': 'Ninafuatwa na nina hofu sasa',
                'language': 'sw',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['language'], 'sw')
        self.assertTrue(response.data['escalate_to_emergency'])
        self.assertEqual(response.data['hotline_number'], '+254119')
        self.assertGreaterEqual(len(response.data['quick_replies']), 1)