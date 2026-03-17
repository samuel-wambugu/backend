from unittest.mock import patch

from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase

from alerts.models import EmergencyContact


class EmergencyContactsApiTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username='owner_user',
            email='owner@example.com',
            password='StrongPass123!',
        )
        self.owner.profile.phone_number = '+254700000201'
        self.owner.profile.save(update_fields=['phone_number'])

        self.contact_user = User.objects.create_user(
            username='contact_user',
            email='contact@example.com',
            password='StrongPass123!',
        )
        self.contact_user.profile.phone_number = '+254700000202'
        self.contact_user.profile.save(update_fields=['phone_number'])

        self.client.force_authenticate(user=self.owner)

    @patch('alerts.views.AlertService.send_email_alert', return_value={'success': True})
    @patch('alerts.views.AlertService.send_sms_alert', return_value={'success': True})
    def test_create_contact_requires_existing_app_account_and_sends_notifications(
        self,
        mock_sms,
        mock_email,
    ):
        response = self.client.post(
            '/api/alerts/contacts/',
            {
                'name': 'Contact User',
                'phone_number': '+254700000202',
                'email': 'contact@example.com',
                'relationship': 'friend',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(EmergencyContact.objects.filter(user=self.owner, email='contact@example.com').exists())
        mock_sms.assert_called_once()
        mock_email.assert_called_once()

    @patch('alerts.views.AlertService.send_email_alert', return_value={'success': True})
    @patch('alerts.views.AlertService.send_sms_alert', return_value={'success': True})
    def test_create_unknown_contact_creates_pending_invite_and_notifies(
        self,
        mock_sms,
        mock_email,
    ):
        response = self.client.post(
            '/api/alerts/contacts/',
            {
                'name': 'Unknown Person',
                'phone_number': '+254799999999',
                'email': 'unknown@example.com',
                'relationship': 'friend',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['is_registered_user'], False)
        contact = EmergencyContact.objects.get(user=self.owner, email='unknown@example.com')
        self.assertTrue(contact.is_active)
        mock_sms.assert_called_once()
        mock_email.assert_called_once()

    def test_create_contact_rejects_unknown_account(self):
        response = self.client.post('/api/alerts/contacts/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_contact_can_remove_self_from_other_users_lists(self):
        EmergencyContact.objects.create(
            user=self.owner,
            name='Contact User',
            phone_number='+254700000202',
            email='contact@example.com',
            relationship='friend',
        )

        self.client.force_authenticate(user=self.contact_user)
        response = self.client.post('/api/alerts/contacts/remove_self/', {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['removed'], 1)
        self.assertFalse(EmergencyContact.objects.filter(user=self.owner, email='contact@example.com').exists())
