from unittest.mock import patch
from typing import Any, cast

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase

from alerts.models import Alert, SafeCheckIn
from alerts.tasks import evaluate_safe_checkin


class SafeCheckInApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='checkin-user', password='StrongPass123!')
        self.client.force_authenticate(user=self.user)

    @patch('alerts.views.evaluate_safe_checkin.apply_async')
    def test_create_safe_checkin_schedules_followup(self, mock_apply_async):
        scheduled_for = timezone.now() + timezone.timedelta(minutes=30)
        response = self.client.post(
            '/api/alerts/checkins/',
            {
                'title': 'Arrive home',
                'note': 'Walking from town',
                'scheduled_for': scheduled_for.isoformat(),
                'grace_minutes': 10,
                'destination': 'Home',
                'location_snapshot': {'latitude': -1.2, 'longitude': 36.8},
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['status'], 'scheduled')
        mock_apply_async.assert_called_once()

    def test_complete_safe_checkin(self):
        checkin = SafeCheckIn.objects.create(
            user=self.user,
            title='Reach office',
            scheduled_for=timezone.now() + timezone.timedelta(minutes=20),
        )

        response = self.client.post(
            f'/api/alerts/checkins/{checkin.id}/complete/',
            {'note': 'Reached safely'},
            format='json',
        )

        self.assertEqual(response.status_code, 200)
        checkin.refresh_from_db()
        self.assertEqual(checkin.status, 'completed')
        self.assertIsNotNone(checkin.completed_at)


class SafeCheckInTaskTests(TestCase):
    @patch('alerts.tasks.send_emergency_alert.delay')
    def test_missed_checkin_creates_alert_and_escalates(self, mock_send_alert):
        user = User.objects.create_user(username='late-user', password='StrongPass123!')
        checkin = SafeCheckIn.objects.create(
            user=user,
            title='Arrive destination',
            note='No response expected after meeting',
            scheduled_for=timezone.now() - timezone.timedelta(minutes=30),
            grace_minutes=5,
            location_snapshot={'latitude': -1.2, 'longitude': 36.8},
        )

        result = cast(Any, evaluate_safe_checkin).run(checkin.id)

        checkin.refresh_from_db()
        self.assertEqual(checkin.status, 'missed')
        self.assertIsNotNone(checkin.escalated_alert)
        self.assertEqual(checkin.escalated_alert.alert_type, 'checkin_missed')
        self.assertTrue(Alert.objects.filter(id=checkin.escalated_alert_id).exists())
        mock_send_alert.assert_called_once_with(checkin.escalated_alert_id)
        self.assertTrue(result['escalated'])
