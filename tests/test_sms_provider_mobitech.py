import sys
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings

from alerts.services import AlertService


class AfricasTalkingSmsProviderTests(SimpleTestCase):
    """Tests for the Africa's Talking SMS provider integration."""

    def _make_service_with_mock_at(self, sender_id='GBVAlert'):
        """Create an AlertService with the Africa's Talking module mocked."""
        mock_sms_service = MagicMock()
        mock_sms_service.send.return_value = {
            'SMSMessageData': {
                'Recipients': [{'status': 'Success', 'number': '+254712244243'}]
            }
        }
        mock_at = MagicMock()
        mock_at.SMS = mock_sms_service
        with patch.dict(sys.modules, {'africastalking': mock_at}), \
             self.settings(
                AFRICASTALKING_API_KEY='test-api-key',
                AFRICASTALKING_USERNAME='sandbox',
                AFRICASTALKING_SENDER_ID=sender_id,
            ):
            service = AlertService()
        # service.sms is now the MagicMock set during __init__
        return service, mock_sms_service

    @override_settings(
        SMS_PROVIDER='africastalking',
        AFRICASTALKING_API_KEY='test-api-key',
        AFRICASTALKING_USERNAME='sandbox',
        AFRICASTALKING_SENDER_ID='GBVAlert',
    )
    def test_send_sms_alert_uses_africastalking_sdk(self):
        mock_sms_service = MagicMock()
        mock_sms_service.send.return_value = {
            'SMSMessageData': {
                'Recipients': [{'status': 'Success', 'number': '+254712244243'}]
            }
        }
        mock_at = MagicMock()
        mock_at.SMS = mock_sms_service

        with patch.dict(sys.modules, {'africastalking': mock_at}):
            service = AlertService()

        result = service.send_sms_alert('254712244243', 'Emergency test', alert_id=7)

        self.assertTrue(result['success'])
        mock_sms_service.send.assert_called_once()
        call_args = mock_sms_service.send.call_args
        # Positional args: (message, recipients_list, ...)
        self.assertEqual(call_args.args[0], 'Emergency test')
        self.assertIn('+254712244243', call_args.args[1])

    @override_settings(
        SMS_PROVIDER='africastalking',
        AFRICASTALKING_API_KEY='test-api-key',
        AFRICASTALKING_USERNAME='sandbox',
        AFRICASTALKING_SENDER_ID='GBVAlert',
    )
    def test_send_sms_alert_accepts_phone_list(self):
        mock_sms_service = MagicMock()
        mock_sms_service.send.return_value = {
            'SMSMessageData': {
                'Recipients': [{'status': 'Success', 'number': '+254712244243'}]
            }
        }
        mock_at = MagicMock()
        mock_at.SMS = mock_sms_service

        with patch.dict(sys.modules, {'africastalking': mock_at}):
            service = AlertService()

        result = service.send_sms_alert(['+254712244243'], 'Emergency test', alert_id=7)

        self.assertTrue(result['success'])
        mock_sms_service.send.assert_called_once()

    def test_send_sms_alert_returns_failure_when_not_configured(self):
        """When AT credentials are absent, send_sms_alert returns success=False."""
        with self.settings(
            SMS_PROVIDER='africastalking',
            AFRICASTALKING_API_KEY='',
            AFRICASTALKING_USERNAME='',
        ):
            service = AlertService()

        result = service.send_sms_alert('+254712244243', 'Emergency test', alert_id=7)

        self.assertFalse(result['success'])
        self.assertIn('error', result)
