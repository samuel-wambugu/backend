import logging
import os
import json
import re
from urllib import request as urllib_request
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from django.conf import settings
from django.core.mail import send_mail
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from typing import Any

# Firebase
import firebase_admin
from firebase_admin import credentials, messaging

# Twilio for voice calls
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse

# Models
from .models import Alert, AlertLog, EmergencyContact
from users.models import UserProfile

logger = logging.getLogger(__name__)

DEFAULT_AUTHORITY_ALERT_CONTACTS = [
    {'name': 'Central Police Station', 'phone_number': '+254202222222'},
    {'name': 'Kilimani Police Station', 'phone_number': '+254203333333'},
    {'name': 'Muthaiga Police Station', 'phone_number': '+254204444444'},
]


class AlertService:
    """Service for sending emergency alerts via Africa's Talking SMS, push, email, and optional voice calls."""

    def __init__(self):
        # SMS provider – driven by SMS_PROVIDER setting so it can be changed without code edits
        self.sms_provider = getattr(settings, 'SMS_PROVIDER', 'mobitech').strip().lower()

        # Africa's Talking (used when SMS_PROVIDER=africastalking)
        self.sms = None
        self.sender_id = ''
        if self.sms_provider == 'africastalking':
            at_key = getattr(settings, 'AFRICASTALKING_API_KEY', '').strip()
            at_user = getattr(settings, 'AFRICASTALKING_USERNAME', '').strip()
            if not at_key or not at_user:
                logger.warning("Africa's Talking SMS not configured properly")
            else:
                import africastalking
                africastalking.initialize(at_user, at_key)
                self.sms = africastalking.SMS
                self.sender_id = getattr(settings, 'AFRICASTALKING_SENDER_ID', '').strip()

        # Twilio setup for voice calls (optional)
        self.twilio_client = None
        if getattr(settings, 'TWILIO_ACCOUNT_SID', None) and getattr(settings, 'TWILIO_AUTH_TOKEN', None):
            self.twilio_client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

        # Firebase setup
        cred_path = getattr(settings, 'FIREBASE_CREDENTIALS_PATH', None)
        if cred_path and os.path.exists(cred_path):
            if not firebase_admin._apps:
                cred = credentials.Certificate(cred_path)
                firebase_admin.initialize_app(cred)

    def _normalize_phone_number(self, phone_number):
        if not phone_number:
            return ''
        normalized = ''.join(ch for ch in str(phone_number).strip() if ch.isdigit() or ch == '+')
        if normalized.startswith('00'):
            normalized = f'+{normalized[2:]}'
        if normalized.count('+') > 1:
            normalized = normalized.replace('+', '')
            normalized = f'+{normalized}'
        if normalized and not normalized.startswith('+'):
            digits_only = normalized.replace('+', '')
            if digits_only.startswith('0') and len(digits_only) == 10:
                normalized = f'+254{digits_only[1:]}'
            elif digits_only.startswith('254') and 12 <= len(digits_only) <= 15:
                normalized = f'+{digits_only}'
        return normalized

    # -------------------
    # SMS
    # -------------------
    def send_sms_alert(self, phone_numbers, message, alert_id=None):
        """Send SMS via configured provider. Accepts a single number string or a list."""
        if isinstance(phone_numbers, str):
            phone_numbers = [self._normalize_phone_number(phone_numbers)]
        else:
            phone_numbers = [self._normalize_phone_number(p) for p in phone_numbers]
        phone_numbers = [p for p in phone_numbers if p]
        if not phone_numbers:
            return {'success': False, 'error': 'No valid phone numbers provided'}

        # Try configured provider first, then fail over to other configured providers.
        providers = [self.sms_provider, 'twilio', 'mobitech', 'africastalking']
        tried = set()
        attempts = []

        for provider in providers:
            if provider in tried:
                continue
            tried.add(provider)

            if provider == 'twilio':
                result = self._send_twilio_sms(phone_numbers, message, alert_id)
            elif provider == 'mobitech':
                result = self._send_mobitech_sms(phone_numbers, message, alert_id)
            elif provider == 'africastalking':
                result = self._send_africastalking_sms(phone_numbers, message, alert_id)
            else:
                continue

            attempts.append({'provider': provider, 'result': result})
            if result.get('success'):
                result['provider'] = provider
                if len(attempts) > 1:
                    result['fallback_used'] = True
                    result['attempts'] = attempts
                return result

        return {
            'success': False,
            'error': 'All configured SMS providers failed',
            'attempts': attempts,
        }

    def _send_twilio_sms(self, phone_numbers, message, alert_id=None):
        """Send SMS via Twilio Messaging API."""
        if not self.twilio_client:
            return {'success': False, 'error': 'Twilio not configured'}
        from_number = getattr(settings, 'TWILIO_PHONE_NUMBER', '').strip()
        if not from_number:
            return {'success': False, 'error': 'TWILIO_PHONE_NUMBER not set'}
        results = []
        any_success = False
        for number in phone_numbers:
            try:
                msg = self.twilio_client.messages.create(
                    body=message,
                    from_=from_number,
                    to=number,
                )
                results.append({'success': True, 'number': number, 'sid': msg.sid, 'status': msg.status})
                any_success = True
            except Exception as exc:
                results.append({'success': False, 'number': number, 'error': str(exc)})
                logger.warning('twilio_sms_failed', extra={'number': number, 'error': str(exc), 'alert_id': alert_id})
        return {'success': any_success, 'results': results}

    def _send_mobitech_sms(self, phone_numbers, message, alert_id=None):
        """Send SMS to each recipient via the Mobitech REST API."""
        api_url = getattr(settings, 'MOBITECH_SMS_API_URL', '').strip()
        api_key = getattr(settings, 'MOBITECH_SMS_API_KEY', '').strip()
        sender_name = getattr(settings, 'MOBITECH_SMS_SENDER_NAME', 'MOBI-TECH').strip()
        service_id = getattr(settings, 'MOBITECH_SMS_SERVICE_ID', 0)
        response_type = getattr(settings, 'MOBITECH_SMS_RESPONSE_TYPE', 'json').strip()

        if not api_url or not api_key:
            logger.warning('mobitech_sms_not_configured')
            return {'success': False, 'error': 'Mobitech SMS not configured'}

        results = []
        any_success = False
        for number in phone_numbers:
            payload = json.dumps({
                'mobile': number,
                'sender_name': sender_name,
                'service_id': service_id,
                'response_type': response_type,
                'message': message,
            }).encode('utf-8')
            req = urllib_request.Request(
                api_url,
                data=payload,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {api_key}',
                },
                method='POST',
            )
            try:
                with urllib_request.urlopen(req, timeout=15) as resp:
                    body = resp.read()
                    try:
                        data = json.loads(body)
                    except json.JSONDecodeError:
                        data = {'raw': body.decode('utf-8', errors='replace')}
                    results.append({'success': True, 'number': number, 'response': data})
                    any_success = True
            except urllib_error.HTTPError as http_err:
                results.append({'success': False, 'number': number, 'error': f'HTTP {http_err.code}: {http_err.reason}'})
                logger.warning('mobitech_sms_failed', extra={'number': number, 'error': str(http_err), 'alert_id': alert_id})
            except Exception as exc:
                results.append({'success': False, 'number': number, 'error': str(exc)})
                logger.warning('mobitech_sms_failed', extra={'number': number, 'error': str(exc), 'alert_id': alert_id})
        return {'success': any_success, 'results': results}

    def _send_africastalking_sms(self, phone_numbers, message, alert_id=None):
        """Send SMS via Africa's Talking SDK."""
        if not self.sms:
            return {'success': False, 'error': "Africa's Talking not configured"}
        try:
            response = self.sms.send(message, phone_numbers, from_=self.sender_id)
            return {'success': True, 'response': response}
        except Exception as exc:
            logger.warning('sms_send_failed', extra={'alert_id': alert_id, 'error': str(exc)})
            return {'success': False, 'error': str(exc)}

    # -------------------
    # Location Formatting
    # -------------------
    def _format_location(self, location):
        """Generate exact live OpenStreetMap location link and coordinates."""
        if not location:
            return "📍 Location: Not available"

        lat = location.get('latitude') or location.get('lat')
        lon = location.get('longitude') or location.get('lng')
        address_fresh = bool(location.get('address_fresh'))
        quality = str(location.get('location_quality') or '').strip().lower()
        address_parts = []
        for key in ('address', 'address_line', 'place_name', 'locality', 'region', 'country'):
            val = location.get(key)
            if val:
                address_parts.append(val.strip())

        osm_link = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}&zoom=18" if lat and lon else ''
        lines = ["📍 Live Location:"]
        if lat and lon:
            lines.append(f"Exact Coordinates (GPS): {lat}, {lon}")
        if address_parts and (address_fresh or quality == 'fresh'):
            lines.append(f"Nearby address (fresh): {'; '.join(address_parts)}")
        elif address_parts:
            lines.append("Nearby address omitted because it may be stale; use GPS/map link above.")
        if osm_link:
            lines.append(f"Map Link: {osm_link}")
        return '\n'.join(lines)

    # -------------------
    # Dynamic Authority Contacts
    # -------------------
    def _generate_dynamic_authority_contacts(self, location):
        """
        Generate authority contacts based on user's current location.
        Replace with AI/geolocation API for real-world nearby police stations.
        """
        latitude = location.get('latitude')
        longitude = location.get('longitude')
        # Example placeholders, replace with dynamic data/API
        return [
            {'name': 'Nearest Police Station 1', 'phone_number': '+254701111111'},
            {'name': 'Nearest Police Station 2', 'phone_number': '+254702222222'},
            {'name': 'Nearest Police Station 3', 'phone_number': '+254703333333'},
        ]

    # -------------------
    # Dispatch Message
    # -------------------
    def _dispatch_message(self, alert):
        """Build emergency alert message with exact live location."""
        user_name = alert.user.username
        location_block = self._format_location(alert.location)
        return (
            f"🚨 EMERGENCY ALERT 🚨\n\n"
            f"User {user_name} is in DANGER and requires immediate assistance!\n\n"
            f"{location_block}\n\n"
            f"⚠️ Please respond immediately and contact authorities!\n"
            f"Triggered by: {user_name}"
        )

    # -------------------
    # Voice Calls
    # -------------------
    def send_voice_call_alert(self, phone_number, message, alert_id=None):
        """Optional: Place a voice call alert via Twilio."""
        if not self.twilio_client or not getattr(settings, 'TWILIO_PHONE_NUMBER', None):
            return {'success': False, 'error': 'Twilio not configured'}

        normalized_phone = self._normalize_phone_number(phone_number)
        if not normalized_phone:
            return {'success': False, 'error': 'Missing phone number'}

        try:
            voice_response = VoiceResponse()
            voice_response.say(
                'Emergency alert from GBV safety application.',
                voice='alice',
                language='en-US',
            )
            voice_response.pause(length=1)
            voice_response.say(message, voice='alice', language='en-US')
            call = self.twilio_client.calls.create(
                twiml=str(voice_response),
                from_=settings.TWILIO_PHONE_NUMBER,
                to=normalized_phone,
            )
            return {'success': True, 'sid': call.sid, 'status': call.status}
        except Exception as e:
            logger.warning("voice_call_send_failed", extra={'phone_number': phone_number, 'error': str(e)})
            return {'success': False, 'error': str(e)}

    # -------------------
    # Push Notifications
    # -------------------
    def send_push_notification(self, device_token, title, body, data=None, alarm=False):
        """Send push notification via Firebase."""
        try:
            if alarm:
                android_notification = messaging.AndroidNotification(
                    sound='default', channel_id='emergency_alarm', priority='max'
                )
                apns_config = messaging.APNSConfig(
                    headers={'apns-priority': '10'},
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(sound='default', badge=1),
                    ),
                )
            else:
                android_notification = messaging.AndroidNotification(sound='default')
                apns_config = messaging.APNSConfig(
                    payload=messaging.APNSPayload(aps=messaging.Aps(sound='default')),
                )

            message = messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data=data or {},
                android=messaging.AndroidConfig(priority='high', notification=android_notification),
                apns=apns_config,
                token=device_token,
            )
            response = messaging.send(message)
            return {'success': True, 'response': response}
        except Exception as e:
            logger.warning("push_send_failed", extra={'error': str(e)})
            return {'success': False, 'error': str(e)}

    # -------------------
    # Email
    # -------------------
    def send_email_alert(self, email, subject, message):
        """Send emergency email."""
        try:
            target_email = (email or '').strip()
            if not target_email:
                return {'success': False, 'error': 'Missing email recipient'}

            escaped = message.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            html_body = re.sub(r'(https?://\S+)', r'<a href="\1">\1</a>', escaped.replace('\n', '<br>\n'))
            html_message = f'<html><body style="font-family:sans-serif;font-size:15px;">{html_body}</body></html>'
            sent_count = send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [target_email],
                html_message=html_message,
                fail_silently=False,
            )
            if sent_count and sent_count > 0:
                return {'success': True, 'sent_count': sent_count, 'recipient': target_email}
            return {
                'success': False,
                'error': 'Email backend did not report a successful send',
                'sent_count': sent_count,
                'recipient': target_email,
            }
        except Exception as e:
            logger.warning("email_send_failed", extra={'email': email, 'error': str(e)})
            return {'success': False, 'error': str(e)}

    # -------------------
    # Authority / Owner / Broadcast Helpers
    # -------------------
    def _authority_contacts(self):
        configured = getattr(settings, 'AUTHORITY_ALERT_CONTACTS', DEFAULT_AUTHORITY_ALERT_CONTACTS)
        if isinstance(configured, str):
            try:
                configured = json.loads(configured)
            except json.JSONDecodeError:
                configured = DEFAULT_AUTHORITY_ALERT_CONTACTS
        return configured or DEFAULT_AUTHORITY_ALERT_CONTACTS

    def get_owner_users(self):
        owner_usernames = set(getattr(settings, 'AI_OWNER_USERNAMES', []))
        owner_filter = Q(is_superuser=True)
        if owner_usernames:
            owner_filter |= Q(username__in=owner_usernames)
        return get_user_model().objects.filter(owner_filter, is_active=True).distinct()

    def _log_channel_result(self, alert, channel, result, *, contact=None, extra=None):
        response = dict(result)
        if extra:
            response.update(extra)
        AlertLog.objects.create(
            alert=alert,
            contact=contact,
            channel=channel,
            status='sent' if result.get('success') else 'failed',
            response=str(response),
        )

    def _resolve_registered_contact_user(self, contact):
        user_model = get_user_model()
        email = (contact.email or '').strip()
        phone_number = (contact.phone_number or '').strip()

        by_email = (
            user_model.objects.filter(email__iexact=email, is_active=True).first()
            if email else None
        )
        by_phone = (
            user_model.objects.filter(profile__phone_number=phone_number, is_active=True).first()
            if phone_number else None
        )

        if by_email and by_phone and by_email.id != by_phone.id:
            return None
        return by_email or by_phone

    def _send_authority_notifications(self, alert, message):
        results = []
        for authority in self._authority_contacts():
            phone = authority.get('phone_number') or authority.get('phone')
            if not phone:
                continue
            sms_result = self.send_sms_alert(
                phone, f'AUTHORITY ALERT: {message}', alert_id=alert.id
            )
            self._log_channel_result(
                alert, 'AuthoritySMS', sms_result,
                extra={'authority_name': authority.get('name', 'Authority')},
            )
            results.append(sms_result)
        return results

    def _send_owner_notifications(self, alert, message):
        results: dict[str, list] = {'sms': [], 'push': [], 'email': []}
        for owner in self.get_owner_users().exclude(id=alert.user_id).select_related('profile'):
            profile = getattr(owner, 'profile', None)

            if profile and profile.phone_number:
                sms_result = self.send_sms_alert(
                    profile.phone_number, f'OWNER ALERT: {message}', alert_id=alert.id
                )
                self._log_channel_result(
                    alert, 'OwnerSMS', sms_result, extra={'owner': owner.username}
                )
                results['sms'].append(sms_result)

            if owner.email:
                email_result = self.send_email_alert(
                    owner.email, '🚨 GBV Owner Emergency Alert', message
                )
                self._log_channel_result(
                    alert, 'OwnerEmail', email_result, extra={'owner': owner.username}
                )
                results['email'].append(email_result)

            if profile and profile.fcm_token:
                push_result = self.send_push_notification(
                    profile.fcm_token,
                    '🚨 Emergency Owner Alert',
                    message,
                    data={
                        'alert_id': str(alert.id),
                        'alert_type': alert.alert_type,
                        'scope': 'owner',
                    },
                )
                self._log_channel_result(
                    alert, 'OwnerPush', push_result, extra={'owner': owner.username}
                )
                results['push'].append(push_result)
                if push_result.get('success'):
                    alert.push_sent = True
        return results

    def _broadcast_to_other_users(self, alert, message):
        results = []
        profiles = UserProfile.objects.select_related('user').filter(
            fcm_token__isnull=False,
            user__is_active=True,
        ).exclude(fcm_token='').exclude(user=alert.user)
        for profile in profiles:
            push_result = self.send_push_notification(
                profile.fcm_token,
                '🚨 Emergency Broadcast',
                message,
                data={
                    'alert_id': str(alert.id),
                    'alert_type': alert.alert_type,
                    'scope': 'community',
                },
            )
            self._log_channel_result(
                alert, 'UserPush', push_result, extra={'username': profile.user.username}
            )
            results.append(push_result)
            if push_result.get('success'):
                alert.push_sent = True
        return results

    # -------------------
    # Escalation Alert Creators
    # -------------------
    def create_checkin_escalation_alert(self, checkin):
        return Alert.objects.create(
            user=checkin.user,
            alert_type='checkin_missed',
            message=f'Safe check-in "{checkin.title}" was missed.',
            location=checkin.location_snapshot,
            priority=4,
        )

    def create_live_session_escalation_alert(self, live_session):
        return Alert.objects.create(
            user=live_session.user,
            alert_type='live_session_missed',
            message=f'Live safety session "{live_session.title}" missed a check-in ping.',
            priority=4,
        )

    # -------------------
    # Send Emergency Alert
    # -------------------
    def send_emergency_alert(self, alert_id):
        """Send alert to all emergency contacts via all available channels."""
        try:
            alert = Alert.objects.get(id=alert_id)
            contacts = EmergencyContact.objects.filter(user=alert.user, is_active=True)
            message = self._dispatch_message(alert)
            contact_delivery_success = False

            results: dict[str, Any] = {
                'sms': [],
                'email': [],
                'voice_calls': [],
                'authority_sms': [],
                'owner_notifications': {'sms': [], 'push': [], 'email': []},
                'user_broadcasts': [],
                'registered_contact_notifications': {'push': [], 'voice_calls': [], 'email': []},
                'active_contact_count': contacts.count(),
                'contacts_notified': False,
            }

            notified_registered_users: set[int] = set()

            for contact in contacts:
                if not (contact.phone_number or contact.email):
                    continue

                registered_user = self._resolve_registered_contact_user(contact)
                registered_profile = (
                    getattr(registered_user, 'profile', None) if registered_user else None
                )
                is_registered = (
                    registered_user is not None and registered_user.id != alert.user_id
                )

                # SMS to contact's phone
                if contact.phone_number:
                    sms_result = self.send_sms_alert(
                        contact.phone_number, message, alert_id=alert_id
                    )
                    AlertLog.objects.create(
                        alert=alert, contact=contact, channel='SMS',
                        status='sent' if sms_result.get('success') else 'failed',
                        response=str(sms_result),
                    )
                    results['sms'].append(sms_result)
                    if sms_result.get('success'):
                        alert.sms_sent = True
                        contact_delivery_success = True

                    # Voice call for manual alerts to non-registered contacts
                    if alert.alert_type == 'manual' and not is_registered:
                        normalized = self._normalize_phone_number(contact.phone_number)
                        if normalized:
                            voice_result = self.send_voice_call_alert(
                                normalized, message, alert_id=alert_id
                            )
                            AlertLog.objects.create(
                                alert=alert, contact=contact, channel='VoiceCall',
                                status='sent' if voice_result.get('success') else 'failed',
                                response=str(voice_result),
                            )
                            results['voice_calls'].append(voice_result)

                # Email to contact
                if contact.email:
                    email_result = self.send_email_alert(
                        contact.email, '🚨 GBV EMERGENCY ALERT', message
                    )
                    AlertLog.objects.create(
                        alert=alert, contact=contact, channel='Email',
                        status='sent' if email_result.get('success') else 'failed',
                        response=str(email_result),
                    )
                    results['email'].append(email_result)
                    if email_result.get('success'):
                        alert.email_sent = True
                        contact_delivery_success = True

                # Registered contact: push + voice + email via their app account
                if is_registered and registered_user.id not in notified_registered_users:
                    notified_registered_users.add(registered_user.id)

                    if registered_profile and registered_profile.fcm_token:
                        push_result = self.send_push_notification(
                            registered_profile.fcm_token,
                            '🚨 Emergency Alert',
                            message,
                            data={
                                'alert_id': str(alert.id),
                                'alert_type': alert.alert_type,
                                'scope': 'emergency-contact',
                                'priority': str(alert.priority),
                            },
                            alarm=True,
                        )
                        AlertLog.objects.create(
                            alert=alert, contact=contact, channel='ContactPush',
                            status='sent' if push_result.get('success') else 'failed',
                            response=str(push_result),
                        )
                        results['registered_contact_notifications']['push'].append(push_result)
                        if push_result.get('success'):
                            alert.push_sent = True
                            contact_delivery_success = True

                    reg_phone = self._normalize_phone_number(
                        getattr(registered_profile, 'phone_number', '') or contact.phone_number or ''
                    )
                    if reg_phone:
                        voice_result = self.send_voice_call_alert(
                            reg_phone, message, alert_id=alert_id
                        )
                        AlertLog.objects.create(
                            alert=alert, contact=contact, channel='RegisteredContactVoiceCall',
                            status='sent' if voice_result.get('success') else 'failed',
                            response=str(voice_result),
                        )
                        results['registered_contact_notifications']['voice_calls'].append(voice_result)
                        if voice_result.get('success'):
                            contact_delivery_success = True

                    target_email = (
                        (registered_user.email or '').strip() or (contact.email or '').strip()
                    )
                    if target_email:
                        email_result = self.send_email_alert(
                            target_email, '🚨 GBV EMERGENCY ALERT', message
                        )
                        AlertLog.objects.create(
                            alert=alert, contact=contact, channel='RegisteredContactEmail',
                            status='sent' if email_result.get('success') else 'failed',
                            response=str(email_result),
                        )
                        results['registered_contact_notifications']['email'].append(email_result)
                        if email_result.get('success'):
                            alert.email_sent = True
                            contact_delivery_success = True

            results['authority_sms'] = self._send_authority_notifications(alert, message)
            results['owner_notifications'] = self._send_owner_notifications(alert, message)
            results['user_broadcasts'] = self._broadcast_to_other_users(alert, message)

            results['contacts_notified'] = contact_delivery_success
            delivered = contact_delivery_success
            alert.status = 'sent' if delivered else 'failed'
            alert.save()
            if not delivered:
                results['error'] = 'Emergency contacts did not receive any notification'
            return results

        except Exception as e:
            logger.exception('emergency_alert_failed', extra={'alert_id': alert_id, 'error': str(e)})
            return {'error': str(e)}