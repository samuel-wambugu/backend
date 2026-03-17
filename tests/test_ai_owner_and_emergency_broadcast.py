from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.test import APITestCase

from alerts.models import Alert, AlertLog, EmergencyContact
from alerts.services import AlertService
from ai_gateway.models import AIOwnerInboxThread


class AiOwnerAssistApiTests(APITestCase):
    def setUp(self):
        self.requester = User.objects.create_user(
            username='requester',
            email='requester@example.com',
            password='StrongPass123!',
        )
        self.owner = User.objects.create_superuser(
            username='owner',
            email='owner@example.com',
            password='StrongPass123!',
        )
        self.owner.profile.phone_number = '+254700000001'
        self.owner.profile.fcm_token = 'owner-token'
        self.owner.profile.save(update_fields=['phone_number', 'fcm_token'])
        self.client.force_authenticate(user=self.requester)

    @patch('alerts.services.AlertService.send_email_alert', return_value={'success': True})
    @patch('alerts.services.AlertService.send_push_notification', return_value={'success': True})
    @patch('alerts.services.AlertService.send_sms_alert', return_value={'success': True})
    def test_contact_owner_endpoint_notifies_available_channels(self, mock_sms, mock_push, mock_email):
        response = self.client.post(
            '/api/ai/chatbot/contact-owner/',
            {
                'message': 'I need direct help from the owner',
                'conversation_summary': 'User asked for escalation after chatbot session.',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['owners_contacted'], 1)
        self.assertEqual(response.data['sms_sent'], 1)
        self.assertEqual(response.data['push_sent'], 1)
        self.assertEqual(response.data['email_sent'], 1)
        self.assertIn('thread_id', response.data)
        self.assertTrue(AIOwnerInboxThread.objects.filter(id=response.data['thread_id']).exists())
        mock_sms.assert_called()
        mock_push.assert_called()
        mock_email.assert_called()

    def test_requester_can_list_and_reply_to_owner_inbox_thread(self):
        contact_response = self.client.post(
            '/api/ai/chatbot/contact-owner/',
            {
                'message': 'Please follow up with me',
                'conversation_summary': 'Chatbot escalation requested.',
            },
            format='json',
        )

        self.assertEqual(contact_response.status_code, 200)
        thread_id = contact_response.data['thread_id']

        list_response = self.client.get('/api/ai/inbox/threads/')
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.data), 1)
        self.assertEqual(list_response.data[0]['id'], thread_id)

        detail_response = self.client.get(f'/api/ai/inbox/threads/{thread_id}/')
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(len(detail_response.data['messages']), 1)

        reply_response = self.client.post(
            f'/api/ai/inbox/threads/{thread_id}/messages/',
            {'body': 'Adding more detail for the owner.'},
            format='json',
        )
        self.assertEqual(reply_response.status_code, 201)
        self.assertEqual(reply_response.data['sender_role'], 'user')

    def test_owner_can_open_and_reply_to_assigned_thread(self):
        contact_response = self.client.post(
            '/api/ai/chatbot/contact-owner/',
            {
                'message': 'Need an owner reply',
            },
            format='json',
        )
        thread_id = contact_response.data['thread_id']

        self.client.force_authenticate(user=self.owner)
        list_response = self.client.get('/api/ai/inbox/threads/')
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.data), 1)

        reply_response = self.client.post(
            f'/api/ai/inbox/threads/{thread_id}/messages/',
            {'body': 'Owner follow-up message.'},
            format='json',
        )
        self.assertEqual(reply_response.status_code, 201)
        self.assertEqual(reply_response.data['sender_role'], 'owner')

    @patch('alerts.services.AlertService.send_push_notification', return_value={'success': True})
    def test_reply_posts_push_to_other_side(self, mock_push):
        contact_response = self.client.post(
            '/api/ai/chatbot/contact-owner/',
            {
                'message': 'Need owner follow-up',
            },
            format='json',
        )
        thread_id = contact_response.data['thread_id']

        self.client.post(
            f'/api/ai/inbox/threads/{thread_id}/messages/',
            {'body': 'Any update from owner?'},
            format='json',
        )

        self.client.force_authenticate(user=self.owner)
        self.client.post(
            f'/api/ai/inbox/threads/{thread_id}/messages/',
            {'body': 'Owner reply back to requester.'},
            format='json',
        )

        self.assertGreaterEqual(mock_push.call_count, 2)

    def test_unread_count_updates_and_read_on_detail_view(self):
        contact_response = self.client.post(
            '/api/ai/chatbot/contact-owner/',
            {
                'message': 'Need unread tracking check',
            },
            format='json',
        )
        thread_id = contact_response.data['thread_id']

        self.client.force_authenticate(user=self.owner)
        self.client.post(
            f'/api/ai/inbox/threads/{thread_id}/messages/',
            {'body': 'Owner has replied.'},
            format='json',
        )

        self.client.force_authenticate(user=self.requester)
        list_response = self.client.get('/api/ai/inbox/threads/')
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(list_response.data[0]['unread_count'], 1)

        detail_response = self.client.get(f'/api/ai/inbox/threads/{thread_id}/')
        self.assertEqual(detail_response.status_code, 200)

        list_after_read = self.client.get('/api/ai/inbox/threads/')
        self.assertEqual(list_after_read.status_code, 200)
        self.assertEqual(list_after_read.data[0]['unread_count'], 0)

    def test_owner_can_close_and_reassign_thread(self):
        second_owner = User.objects.create_superuser(
            username='owner3',
            email='owner3@example.com',
            password='StrongPass123!',
        )

        contact_response = self.client.post(
            '/api/ai/chatbot/contact-owner/',
            {
                'message': 'Need assignment update',
            },
            format='json',
        )
        thread_id = contact_response.data['thread_id']

        self.client.force_authenticate(user=self.owner)
        manage_response = self.client.patch(
            f'/api/ai/inbox/threads/{thread_id}/manage/',
            {
                'status': 'closed',
                'assigned_owner_user_id': second_owner.id,
            },
            format='json',
        )

        self.assertEqual(manage_response.status_code, 200)
        self.assertEqual(manage_response.data['status'], 'closed')
        self.assertEqual(manage_response.data['assigned_owner'], second_owner.id)


class ManualEmergencyBroadcastTests(TestCase):
    @patch('alerts.services.AlertService.send_email_alert', return_value={'success': True})
    @patch('alerts.services.AlertService.send_push_notification', return_value={'success': True})
    @patch('alerts.services.AlertService.send_voice_call_alert', return_value={'success': True})
    @patch('alerts.services.AlertService.send_sms_alert', return_value={'success': True})
    def test_manual_alert_broadcasts_to_contacts_authorities_owners_and_other_users(
        self,
        mock_sms,
        mock_voice_call,
        mock_push,
        mock_email,
    ):
        sender = User.objects.create_user(
            username='sender',
            email='sender@example.com',
            password='StrongPass123!',
        )
        owner = User.objects.create_superuser(
            username='owner2',
            email='owner2@example.com',
            password='StrongPass123!',
        )
        owner.profile.phone_number = '+254700000010'
        owner.profile.fcm_token = 'owner-push-token'
        owner.profile.save(update_fields=['phone_number', 'fcm_token'])

        community_user = User.objects.create_user(
            username='community',
            email='community@example.com',
            password='StrongPass123!',
        )
        community_user.profile.fcm_token = 'community-push-token'
        community_user.profile.save(update_fields=['fcm_token'])

        EmergencyContact.objects.create(
            user=sender,
            name='Trusted Friend',
            phone_number='+254711111111',
            email='friend@example.com',
            relationship='friend',
            is_active=True,
        )

        alert = Alert.objects.create(
            user=sender,
            alert_type='manual',
            message='EMERGENCY! I need help immediately.',
            location={'latitude': -1.28, 'longitude': 36.81},
            priority=5,
        )

        service = AlertService()
        results = service.send_emergency_alert(alert.id)

        alert.refresh_from_db()
        self.assertEqual(alert.status, 'sent')
        self.assertTrue(alert.sms_sent)
        self.assertTrue(alert.email_sent)
        self.assertTrue(alert.push_sent)
        self.assertTrue(results['authority_sms'])
        self.assertTrue(results['owner_notifications']['push'])
        self.assertTrue(results['user_broadcasts'])
        self.assertTrue(results['voice_calls'])
        self.assertTrue(AlertLog.objects.filter(alert=alert, channel='AuthoritySMS').exists())
        self.assertTrue(AlertLog.objects.filter(alert=alert, channel='OwnerPush').exists())
        self.assertTrue(AlertLog.objects.filter(alert=alert, channel='UserPush').exists())
        self.assertTrue(AlertLog.objects.filter(alert=alert, channel='VoiceCall').exists())
        mock_voice_call.assert_called()

    @patch('alerts.services.AlertService.send_email_alert', return_value={'success': True})
    @patch('alerts.services.AlertService.send_push_notification', return_value={'success': True})
    @patch('alerts.services.AlertService.send_voice_call_alert', return_value={'success': True})
    @patch('alerts.services.AlertService.send_sms_alert', return_value={'success': True})
    def test_registered_contact_receives_push_voice_and_email_channels(
        self,
        _mock_sms,
        _mock_voice_call,
        _mock_push,
        _mock_email,
    ):
        sender = User.objects.create_user(
            username='sender_reg',
            email='sender_reg@example.com',
            password='StrongPass123!',
        )
        app_contact = User.objects.create_user(
            username='app_contact',
            email='app_contact@example.com',
            password='StrongPass123!',
        )
        app_contact.profile.phone_number = '+254799000111'
        app_contact.profile.fcm_token = 'app-contact-token'
        app_contact.profile.save(update_fields=['phone_number', 'fcm_token'])

        EmergencyContact.objects.create(
            user=sender,
            name='Registered Contact',
            phone_number='+254799000111',
            email='',
            relationship='friend',
            is_active=True,
        )

        alert = Alert.objects.create(
            user=sender,
            alert_type='voice',
            message='I need immediate help.',
            location={'latitude': -1.2, 'longitude': 36.8},
            priority=5,
        )

        service = AlertService()
        results = service.send_emergency_alert(alert.id)

        alert.refresh_from_db()
        self.assertEqual(alert.status, 'sent')
        self.assertTrue(alert.sms_sent)
        self.assertTrue(alert.email_sent)
        self.assertTrue(alert.push_sent)
        self.assertTrue(results['registered_contact_notifications']['push'])
        self.assertTrue(results['registered_contact_notifications']['voice_calls'])
        self.assertTrue(results['registered_contact_notifications']['email'])
        self.assertTrue(AlertLog.objects.filter(alert=alert, channel='ContactPush').exists())
        self.assertTrue(AlertLog.objects.filter(alert=alert, channel='RegisteredContactVoiceCall').exists())
        self.assertTrue(AlertLog.objects.filter(alert=alert, channel='RegisteredContactEmail').exists())


class AlertDeliveryStatusApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='delivery_user',
            email='delivery@example.com',
            password='StrongPass123!',
        )
        self.client.force_authenticate(user=self.user)

    def test_delivery_status_returns_channel_summary(self):
        alert = Alert.objects.create(
            user=self.user,
            alert_type='manual',
            message='Emergency now',
            priority=5,
            status='sent',
        )
        AlertLog.objects.create(alert=alert, channel='SMS', status='sent', response='ok')
        AlertLog.objects.create(alert=alert, channel='SMS', status='failed', response='fail')
        AlertLog.objects.create(alert=alert, channel='VoiceCall', status='sent', response='ok')

        response = self.client.get(f'/api/alerts/alerts/{alert.id}/delivery_status/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['alert_id'], alert.id)
        self.assertEqual(response.data['channels']['SMS']['sent'], 1)
        self.assertEqual(response.data['channels']['SMS']['failed'], 1)
        self.assertEqual(response.data['channels']['VoiceCall']['sent'], 1)

    @patch('alerts.services.AlertService.send_voice_call_alert', return_value={'success': True})
    @patch('alerts.services.AlertService.send_sms_alert', return_value={'success': True})
    def test_retry_failed_channels_retries_latest_per_contact_and_channel(
        self,
        mock_sms,
        mock_voice,
    ):
        alert = Alert.objects.create(
            user=self.user,
            alert_type='manual',
            message='Retry emergency',
            priority=5,
            status='failed',
        )
        contact = EmergencyContact.objects.create(
            user=self.user,
            name='Retry Contact',
            phone_number='+254722000123',
            email='retry@example.com',
            relationship='friend',
            is_active=True,
        )

        AlertLog.objects.create(alert=alert, contact=contact, channel='SMS', status='failed', response='first')
        AlertLog.objects.create(alert=alert, contact=contact, channel='SMS', status='failed', response='second')
        AlertLog.objects.create(alert=alert, contact=contact, channel='VoiceCall', status='failed', response='call')

        response = self.client.post(f'/api/alerts/alerts/{alert.id}/retry_failed_channels/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['retried'], 2)
        self.assertEqual(response.data['succeeded'], 2)
        self.assertEqual(response.data['failed'], 0)
        self.assertEqual(mock_sms.call_count, 1)
        self.assertEqual(mock_voice.call_count, 1)
        self.assertEqual(
            AlertLog.objects.filter(alert=alert, status='sent', response__startswith='retry:').count(),
            2,
        )

    def test_retry_failed_channels_returns_empty_when_no_failed_contact_logs(self):
        alert = Alert.objects.create(
            user=self.user,
            alert_type='manual',
            message='No retries needed',
            priority=3,
            status='sent',
        )

        response = self.client.post(f'/api/alerts/alerts/{alert.id}/retry_failed_channels/')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['retried'], 0)
        self.assertEqual(response.data['succeeded'], 0)
        self.assertEqual(response.data['failed'], 0)