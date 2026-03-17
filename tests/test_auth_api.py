from django.contrib.auth.models import User
from unittest.mock import patch
from rest_framework import status
from rest_framework.test import APITestCase
from alerts.models import EmergencyContact
from users.models import EmailVerificationOTP


class AuthApiTests(APITestCase):
    @patch('users.views.send_mail', return_value=1)
    def test_register_user(self, _mock_send_mail):
        response = self.client.post(
            '/api/users/register/',
            {
                'username': 'tester',
                'email': 'tester@example.com',
                'password': 'StrongPass123!',
                'password_confirm': 'StrongPass123!',
                'phone_number': '+1234567890',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(User.objects.filter(username='tester').exists())

    @patch('users.views.send_mail', return_value=1)
    def test_register_auto_activates_matching_pending_contact(self, _mock_send_mail):
        owner = User.objects.create_user(
            username='ownerx',
            email='ownerx@example.com',
            password='StrongPass123!',
        )
        EmergencyContact.objects.create(
            user=owner,
            name='Tester Pending',
            phone_number='+1234567890',
            email='tester@example.com',
            relationship='friend',
            is_active=False,
        )

        response = self.client.post(
            '/api/users/register/',
            {
                'username': 'tester_pending',
                'email': 'tester@example.com',
                'password': 'StrongPass123!',
                'password_confirm': 'StrongPass123!',
                'phone_number': '+1234567890',
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(
            EmergencyContact.objects.filter(user=owner, email='tester@example.com', is_active=True).exists()
        )

    @patch('users.views.send_mail', return_value=1)
    def test_jwt_login_returns_tokens_after_otp_verification(self, _mock_send_mail):
        User.objects.create_user(username='mobile', email='mobile@example.com', password='StrongPass123!')

        request_otp_response = self.client.post(
            '/api/auth/login/',
            {'username': 'mobile', 'password': 'StrongPass123!'},
            format='json',
        )
        self.assertEqual(request_otp_response.status_code, status.HTTP_200_OK)
        self.assertEqual(request_otp_response.data.get('status'), 'otp_sent')

        otp = (
            EmailVerificationOTP.objects
            .filter(user__username='mobile', purpose='login', used_at__isnull=True)
            .order_by('-created_at')
            .first()
        )
        self.assertIsNotNone(otp)

        verify_response = self.client.post(
            '/api/auth/login/verify-otp/',
            {
                'username': 'mobile',
                'password': 'StrongPass123!',
                'otp': otp.code,
            },
            format='json',
        )

        self.assertEqual(verify_response.status_code, status.HTTP_200_OK)
        self.assertIn('access', verify_response.data)
        self.assertIn('refresh', verify_response.data)
