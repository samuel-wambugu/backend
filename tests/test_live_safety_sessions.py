from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from alerts.models import Alert, LiveSafetySession
from alerts.tasks import evaluate_live_session


class LiveSafetySessionApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='session-user', password='StrongPass123!')
        self.client.force_authenticate(user=self.user)

    @patch('alerts.views.evaluate_live_session.apply_async')
    def test_create_live_session_schedules_followup(self, mock_apply_async):
        expires_at = timezone.now() + timezone.timedelta(minutes=45)
        response = self.client.post(
            '/api/alerts/live-sessions/',
            {
                'title': 'Travel home',
                'note': 'Taxi ride',
                'destination': 'Home',
                'check_in_interval_minutes': 10,
                'expires_at': expires_at.isoformat(),
                'current_location': {'latitude': -1.2, 'longitude': 36.8},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'active')
        mock_apply_async.assert_called_once()

    @patch('alerts.views.evaluate_live_session.apply_async')
    def test_ping_live_session_updates_last_ping(self, mock_apply_async):
        live_session = LiveSafetySession.objects.create(
            user=self.user,
            title='Walk home',
            expires_at=timezone.now() + timezone.timedelta(minutes=30),
            last_ping_at=timezone.now() - timezone.timedelta(minutes=5),
        )

        response = self.client.post(
            f'/api/alerts/live-sessions/{live_session.id}/ping/',
            {'note': 'Still on route', 'location': {'latitude': -1.19, 'longitude': 36.82}},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        live_session.refresh_from_db()
        self.assertIsNotNone(live_session.last_ping_at)
        self.assertEqual(live_session.current_location['latitude'], -1.19)
        mock_apply_async.assert_called_once()


class LiveSafetySessionTaskTests(TestCase):
    @patch('alerts.tasks.send_emergency_alert.delay')
    def test_missed_live_session_creates_alert_and_escalates(self, mock_send_alert):
        user = User.objects.create_user(username='offline-user', password='StrongPass123!')
        live_session = LiveSafetySession.objects.create(
            user=user,
            title='Commute',
            note='Call if I miss a ping',
            destination='Shelter',
            check_in_interval_minutes=5,
            expires_at=timezone.now() + timezone.timedelta(minutes=20),
            last_ping_at=timezone.now() - timezone.timedelta(minutes=10),
            current_location={'latitude': -1.2, 'longitude': 36.8},
        )

        result = evaluate_live_session.run(live_session.id)

        live_session.refresh_from_db()
        self.assertEqual(live_session.status, 'escalated')
        self.assertIsNotNone(live_session.escalated_alert)
        self.assertEqual(live_session.escalated_alert.alert_type, 'live_session_missed')
        self.assertTrue(Alert.objects.filter(id=live_session.escalated_alert_id).exists())
        mock_send_alert.assert_called_once_with(live_session.escalated_alert_id)
        self.assertTrue(result['escalated'])