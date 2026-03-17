import logging
import threading
import time
from time import perf_counter

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from incidents.models import Incident
from sensors.models import SensorReading

from .models import (
    AIAuditRecord,
    AIFullAccessGrant,
    AIOwnerInboxMessage,
    AIOwnerInboxThread,
)
from .providers import ProviderConfigurationError, ProviderRequestError, build_provider_registry


logger = logging.getLogger(__name__)


_provider_cooldown_state = {}
_provider_cooldown_lock = threading.Lock()


class AIGatewayService:
    """Helper service to score incidents and optionally call external AI APIs."""

    RISK_KEYWORDS = {
        'critical': ['kill', 'weapon', 'abduct', 'rape', 'bleeding', 'help me now'],
        'high': ['attack', 'threat', 'violence', 'danger', 'scream', 'panic'],
        'medium': ['harass', 'stalk', 'fear', 'unsafe', 'followed'],
    }

    SAFETY_INTENT_RULES = [
        {
            'intent': 'immediate-danger',
            'keywords': ['danger', 'attack', 'help now', 'weapon', 'kill', 'threat', 'violent', 'hatari', 'nasaidiwa', 'silaha', 'nauawa'],
            'tips': {
                'en': [
                    'Prioritize moving to a populated, well-lit place as quickly as possible.',
                    'Call emergency services immediately and share your location clearly.',
                    'Use the emergency alert feature to notify trusted contacts right away.',
                ],
                'sw': [
                    'Kimbilia eneo lenye watu na mwanga wa kutosha haraka iwezekanavyo.',
                    'Piga simu ya dharura mara moja na eleza mahali ulipo kwa uwazi.',
                    'Tumia kipengele cha tahadhari ya dharura kuwajulisha watu unaowaamini.',
                ],
            },
        },
        {
            'intent': 'stalking-or-following',
            'keywords': ['follow', 'stalk', 'watching me', 'tracking me', 'ninafuatwa', 'kunifuatilia', 'ananifuata'],
            'tips': {
                'en': [
                    'Do not go directly home; move to a public space with staff or security.',
                    'Document key details like time, place, appearance, and behavior safely.',
                    'Inform trusted contacts and consider requesting accompaniment for travel.',
                ],
                'sw': [
                    'Usiende moja kwa moja nyumbani; nenda sehemu ya umma yenye usalama.',
                    'Andika maelezo muhimu kama muda, mahali, muonekano na tabia kwa usalama.',
                    'Wajulishe watu unaowaamini na omba kuandamana unaposafiri.',
                ],
            },
        },
        {
            'intent': 'digital-safety',
            'keywords': ['phone', 'online', 'password', 'social media', 'account', 'tracking app', 'simu', 'nenosiri', 'akaunti', 'mtandaoni'],
            'tips': {
                'en': [
                    'Change important account passwords from a device you trust.',
                    'Review app permissions and remove unknown location or microphone access.',
                    'Enable two-factor authentication on key accounts.',
                ],
                'sw': [
                    'Badilisha nywila muhimu kutoka kifaa unachokiamini.',
                    'Kagua ruhusa za programu na ondoa ruhusa za eneo au kipaza sauti zisizojulikana.',
                    'Washa uthibitishaji wa hatua mbili kwenye akaunti muhimu.',
                ],
            },
        },
        {
            'intent': 'evidence-and-reporting',
            'keywords': ['report', 'evidence', 'police', 'case', 'record', 'ripoti', 'ushahidi', 'polisi', 'kesi', 'rekodi'],
            'tips': {
                'en': [
                    'Save messages, screenshots, photos, and incident notes in one secure place.',
                    'Keep original files whenever possible to preserve metadata.',
                    'Record dates, locations, and witnesses soon after each incident.',
                ],
                'sw': [
                    'Hifadhi ujumbe, picha za skrini, picha na maelezo ya tukio sehemu salama.',
                    'Weka faili asili inapowezekana ili kuhifadhi metadata.',
                    'Andika tarehe, maeneo na mashahidi mapema baada ya kila tukio.',
                ],
            },
        },
        {
            'intent': 'emotional-support',
            'keywords': ['scared', 'anxious', 'panic', 'trauma', 'stressed', 'naogopa', 'wasiwasi', 'hofu', 'msongo'],
            'tips': {
                'en': [
                    'Try a grounding step: inhale for 4 seconds, exhale for 6 seconds, repeat 5 times.',
                    'Reach out to a trusted person and tell them what support you need now.',
                    'Contact a local survivor-support organization for confidential help.',
                ],
                'sw': [
                    'Jaribu utulivu wa pumzi: vuta pumzi sekunde 4, toa sekunde 6, rudia mara 5.',
                    'Wasiliana na mtu unaemwamini na umwambie msaada unaohitaji sasa.',
                    'Wasiliana na taasisi ya msaada kwa manusura kwa usaidizi wa siri.',
                ],
            },
        },
    ]

    def __init__(self):
        self.providers = build_provider_registry()

    def provider_status(self):
        active_provider = settings.AI_PROVIDER if settings.AI_PROVIDER in self.providers else ''
        return {
            'active_provider': active_provider,
            'providers': [provider.get_status() for provider in self.providers.values()],
        }

    def is_owner_user(self, user):
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        owner_usernames = set(getattr(settings, 'AI_OWNER_USERNAMES', []))
        return bool(user.is_superuser or user.username in owner_usernames)

    def get_owner_users(self):
        owner_usernames = set(getattr(settings, 'AI_OWNER_USERNAMES', []))
        owner_filter = Q(is_superuser=True)
        if owner_usernames:
            owner_filter |= Q(username__in=owner_usernames)
        return get_user_model().objects.filter(owner_filter, is_active=True).distinct()

    def get_owner_inbox_threads_for_user(self, user):
        queryset = AIOwnerInboxThread.objects.select_related(
            'requester', 'assigned_owner'
        ).prefetch_related('messages')
        if self.is_owner_user(user):
            return queryset.filter(Q(assigned_owner=user) | Q(assigned_owner__isnull=True)).distinct()
        return queryset.filter(requester=user)

    def get_owner_inbox_thread_for_user(self, user, thread_id):
        queryset = self.get_owner_inbox_threads_for_user(user)
        try:
            return queryset.get(id=thread_id)
        except AIOwnerInboxThread.DoesNotExist as exc:
            raise PermissionDenied('Inbox thread not available.') from exc

    def mark_owner_inbox_thread_read(self, thread, user):
        if self.is_owner_user(user):
            if thread.owner_last_read_at != thread.last_message_at:
                thread.owner_last_read_at = thread.last_message_at
                thread.save(update_fields=['owner_last_read_at', 'updated_at'])
            return

        if thread.requester_id == user.id and thread.requester_last_read_at != thread.last_message_at:
            thread.requester_last_read_at = thread.last_message_at
            thread.save(update_fields=['requester_last_read_at', 'updated_at'])

    def update_owner_inbox_thread(
        self,
        thread,
        actor,
        *,
        status=None,
        assigned_owner_user_id=None,
        assigned_owner_provided=False,
    ):
        if not self.is_owner_user(actor):
            raise PermissionDenied('Only owner accounts can manage inbox threads.')

        update_fields = ['updated_at']

        if status is not None:
            thread.status = status
            update_fields.append('status')

        if assigned_owner_provided:
            if assigned_owner_user_id is None:
                thread.assigned_owner = None
            else:
                try:
                    assigned_owner = self.get_owner_users().get(id=assigned_owner_user_id)
                except get_user_model().DoesNotExist as exc:
                    raise ValidationError('Selected owner account is not available.') from exc
                thread.assigned_owner = assigned_owner
            update_fields.append('assigned_owner')

        thread.save(update_fields=update_fields)
        return thread

    def _notify_owner_inbox_counterpart(self, thread, message):
        from alerts.services import AlertService

        alert_service = AlertService()
        sender_role = message.sender_role

        if sender_role == 'owner':
            targets = [thread.requester]
            title = 'New owner inbox reply'
        else:
            if thread.assigned_owner_id:
                targets = [thread.assigned_owner]
            else:
                targets = list(self.get_owner_users().exclude(id=message.sender_id))
            title = 'User replied in owner inbox'

        preview = (message.body or '').strip()
        body = preview[:160] if preview else 'You have a new message in Owner Inbox.'

        for target in targets:
            profile = getattr(target, 'profile', None)
            token = getattr(profile, 'fcm_token', '') if profile else ''
            if not token:
                continue
            alert_service.send_push_notification(
                token,
                title,
                body,
                data={
                    'scope': 'ai-owner-inbox',
                    'thread_id': str(thread.id),
                    'sender_role': sender_role,
                },
            )

    def create_owner_inbox_message(self, thread, sender, body):
        if thread.status == 'closed':
            raise ValidationError('This inbox thread is closed. Reopen it before replying.')

        sender_role = 'owner' if self.is_owner_user(sender) else 'user'
        message = AIOwnerInboxMessage.objects.create(
            thread=thread,
            sender=sender,
            sender_role=sender_role,
            body=body.strip(),
        )
        if sender_role == 'owner' and thread.assigned_owner_id is None:
            thread.assigned_owner = sender
        if sender_role == 'owner':
            thread.owner_last_read_at = message.created_at
        else:
            thread.requester_last_read_at = message.created_at
        thread.last_message_at = message.created_at
        thread.save(
            update_fields=[
                'assigned_owner',
                'requester_last_read_at',
                'owner_last_read_at',
                'last_message_at',
                'updated_at',
            ]
        )
        self._notify_owner_inbox_counterpart(thread, message)
        return message

    def has_owner_approved_full_access(self, user):
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        if self.is_owner_user(user):
            return True
        return AIFullAccessGrant.objects.filter(
            grantee=user,
            is_active=True,
            can_use_all_features=True,
            owner__is_active=True,
        ).exists()

    def analyze_incident(self, payload, user=None):
        text = ' '.join([
            payload.get('title', ''),
            payload.get('description', ''),
            payload.get('transcription', ''),
        ]).lower()

        score = self._keyword_risk_score(text)
        urgency = self._urgency_from_score(score)
        actions = self._recommended_actions(urgency)
        moderation_flags = self._moderation_flags(payload)

        request_metadata = {
            'title_length': len(payload.get('title', '')),
            'description_length': len(payload.get('description', '')),
            'has_transcription': bool(payload.get('transcription')),
            'has_location': bool(payload.get('location')),
        }

        response = {
            'risk_score': score,
            'urgency': urgency,
            'recommended_actions': actions,
            'provider_status': self.provider_status(),
            'moderation_flags': moderation_flags,
            'external_ai_used': False,
        }
        self._enrich_explainability(response, payload)

        audit = self._dispatch_analysis(
            endpoint_name='incident-analysis',
            payload=payload,
            response=response,
            user=user,
            moderation_flags=moderation_flags,
            request_metadata=request_metadata,
        )
        response['audit_id'] = audit.id

        return response

    def triage_incident(self, incident, *, dry_run=True, provider_name='', sensor_limit=5, user=None):
        voice_transcript = ''
        voice_recording = incident.voice_recording
        if voice_recording and voice_recording.transcription:
            voice_transcript = voice_recording.transcription

        sensor_readings = list(
            SensorReading.objects.filter(device__user=incident.reporter, is_anomaly=True)
            .select_related('device')
            .order_by('-timestamp')[:sensor_limit]
        )
        sensor_context = [
            {
                'sensor_type': reading.device.sensor_type,
                'device_name': reading.device.name,
                'value': reading.value,
                'location': reading.location,
                'timestamp': reading.timestamp.isoformat(),
            }
            for reading in sensor_readings
        ]
        payload = {
            'title': incident.title,
            'description': incident.description,
            'transcription': voice_transcript,
            'location': incident.location or (voice_recording.location if voice_recording else None),
            'dry_run': dry_run,
            'provider': provider_name,
            'sensor_context': sensor_context,
            'incident_severity': incident.severity,
            'incident_status': incident.status,
        }
        moderation_flags = self._moderation_flags(payload)
        fallback = self._build_fallback_response(payload)
        fallback['triage_context'] = {
            'incident_id': incident.id,
            'voice_recording_id': voice_recording.id if voice_recording else None,
            'sensor_anomaly_count': len(sensor_context),
            'sensor_context': sensor_context,
            'location': payload['location'],
        }

        request_metadata = {
            'incident_id': incident.id,
            'reporter_id': incident.reporter_id,
            'sensor_anomaly_count': len(sensor_context),
            'has_voice_transcript': bool(voice_transcript),
        }
        audit = self._dispatch_analysis(
            endpoint_name='incident-triage',
            payload=payload,
            response=fallback,
            user=user or incident.reporter,
            incident=incident,
            voice_recording=voice_recording,
            moderation_flags=moderation_flags,
            request_metadata=request_metadata,
        )
        fallback['audit_id'] = audit.id
        return fallback

    def _keyword_risk_score(self, text):
        score = 0
        for keyword in self.RISK_KEYWORDS['medium']:
            if keyword in text:
                score += 10
        for keyword in self.RISK_KEYWORDS['high']:
            if keyword in text:
                score += 20
        for keyword in self.RISK_KEYWORDS['critical']:
            if keyword in text:
                score += 30
        return min(score, 100)

    def _urgency_from_score(self, score):
        if score >= 70:
            return 'critical'
        if score >= 40:
            return 'high'
        if score >= 20:
            return 'medium'
        return 'low'

    def _recommended_actions(self, urgency):
        if urgency == 'critical':
            return [
                'Trigger emergency contacts immediately',
                'Share live location with trusted contacts',
                'Escalate to local emergency services',
            ]
        if urgency == 'high':
            return [
                'Notify emergency contacts',
                'Record additional evidence',
                'Move to a safe location',
            ]
        if urgency == 'medium':
            return [
                'Document the incident details',
                'Alert at least one trusted contact',
            ]
        return [
            'Continue monitoring',
            'Save incident details for follow-up',
        ]

    def _build_fallback_response(self, payload):
        text = ' '.join([
            payload.get('title', ''),
            payload.get('description', ''),
            payload.get('transcription', ''),
            ' '.join(item.get('sensor_type', '') for item in payload.get('sensor_context', [])),
        ]).lower()
        score = self._keyword_risk_score(text)
        score = min(score + (len(payload.get('sensor_context', [])) * 5), 100)
        urgency = self._urgency_from_score(score)
        response = {
            'risk_score': score,
            'urgency': urgency,
            'recommended_actions': self._recommended_actions(urgency),
            'provider_status': self.provider_status(),
            'moderation_flags': self._moderation_flags(payload),
            'external_ai_used': False,
        }
        self._enrich_explainability(response, payload)
        return response

    def _dispatch_analysis(
        self,
        *,
        endpoint_name,
        payload,
        response,
        user=None,
        incident=None,
        voice_recording=None,
        moderation_flags=None,
        request_metadata=None,
    ):
        dry_run = payload.get('dry_run', True)
        requested_provider_name = payload.get('provider') or settings.AI_PROVIDER
        started = perf_counter()
        audit_data = {
            'provider': requested_provider_name or 'fallback',
            'model_name': '',
            'endpoint_name': endpoint_name,
            'dry_run': dry_run,
            'success': True,
            'latency_ms': 0,
            'status_code': 200,
            'moderation_flags': moderation_flags or {},
            'request_metadata': request_metadata or {},
            'request_payload': payload,
            'response_payload': response,
            'external_request_id': '',
            'error_message': '',
            'user': user,
            'incident': incident,
            'voice_recording': voice_recording,
        }

        if not dry_run and not self.has_owner_approved_full_access(user):
            message = 'Owner approval required for full AI functionality.'
            audit_data.update({'success': False, 'status_code': 403, 'error_message': message})
            response['provider_error'] = message

        elif not dry_run:
            attempts = []
            provider_error_messages = []
            provider_order = self._provider_attempt_order(requested_provider_name)
            skipped_unconfigured = []
            skipped_cooldown = []

            for provider_name in provider_order:
                provider = self.providers.get(provider_name)
                if not provider:
                    continue

                if getattr(settings, 'AI_PROVIDER_SKIP_UNCONFIGURED', True) and not provider.is_configured():
                    skipped_unconfigured.append(provider_name)
                    continue

                if self._is_provider_temporarily_blocked(provider_name):
                    skipped_cooldown.append(provider_name)
                    continue

                attempts.append(provider_name)

                try:
                    provider_response = provider.invoke(
                        self._build_messages(payload, endpoint_name),
                        {'temperature': 0.2, 'max_tokens': 600},
                    )
                    parsed = self._parse_provider_text(provider_response['text'])
                    response.update(parsed)
                    response['external_ai_used'] = True
                    response['external_response'] = provider_response['raw_response']
                    response['provider_attempts'] = attempts
                    self._enrich_explainability(response, payload)
                    audit_data.update({
                        'provider': provider_response['provider'],
                        'model_name': provider_response['model_name'],
                        'status_code': provider_response['status_code'],
                        'response_payload': response,
                        'external_request_id': provider_response.get('external_request_id', ''),
                    })
                    provider_error_messages = []
                    break
                except ProviderConfigurationError as exc:
                    skipped_unconfigured.append(provider_name)
                    provider_error_messages.append(f'{provider_name}: {exc}')
                    continue
                except ProviderRequestError as exc:
                    logger.warning('ai_provider_request_failed', extra={'provider': provider_name, 'error': str(exc)})
                    if exc.status_code == 429:
                        self._set_provider_cooldown(provider_name)
                    provider_error_messages.append(f'{provider_name}: {exc}')
                    continue
                except Exception as exc:
                    logger.exception('ai_provider_request_failed', extra={'provider': provider_name, 'error': str(exc)})
                    provider_error_messages.append(f'{provider_name}: {exc}')
                    continue

            if skipped_unconfigured:
                response['providers_skipped_unconfigured'] = skipped_unconfigured
            if skipped_cooldown:
                response['providers_skipped_cooldown'] = skipped_cooldown

            if provider_error_messages:
                error_message = '; '.join(provider_error_messages)
                response['provider_error'] = error_message
                response['provider_attempts'] = attempts
                audit_data.update({'success': False, 'status_code': 502, 'error_message': error_message})

        self._enrich_explainability(response, payload)

        audit_data['latency_ms'] = int((perf_counter() - started) * 1000)
        return AIAuditRecord.objects.create(**audit_data)

    def _build_messages(self, payload, endpoint_name):
        sensor_summary = payload.get('sensor_context', [])
        instructions = (
            'You are a GBV incident triage assistant. '
            'Return only JSON with keys: risk_score, urgency, recommended_actions, moderation_flags.'
        )
        if endpoint_name == 'incident-triage':
            instructions += ' Consider voice transcript, recent sensor anomalies, location context, and incident severity.'

        user_prompt = {
            'title': payload.get('title', ''),
            'description': payload.get('description', ''),
            'transcription': payload.get('transcription', ''),
            'location': payload.get('location'),
            'sensor_context': sensor_summary,
            'incident_severity': payload.get('incident_severity'),
            'incident_status': payload.get('incident_status'),
        }
        return [
            {'role': 'system', 'content': instructions},
            {'role': 'user', 'content': str(user_prompt)},
        ]

    def _provider_attempt_order(self, requested_provider_name):
        order = []
        primary = requested_provider_name or settings.AI_PROVIDER
        if primary:
            order.append(primary)

        failover_order = getattr(settings, 'AI_PROVIDER_FAILOVER_ORDER', [])
        if isinstance(failover_order, str):
            failover_order = [item.strip() for item in failover_order.split(',') if item.strip()]

        for provider_name in failover_order:
            clean_name = (provider_name or '').strip()
            if clean_name and clean_name not in order:
                order.append(clean_name)

        return [name for name in order if name in self.providers]

    def _is_provider_temporarily_blocked(self, provider_name):
        now = time.time()
        with _provider_cooldown_lock:
            cooldown_until = _provider_cooldown_state.get(provider_name)
            if not cooldown_until:
                return False
            if cooldown_until <= now:
                _provider_cooldown_state.pop(provider_name, None)
                return False
            return True

    def _set_provider_cooldown(self, provider_name):
        cooldown_seconds = max(int(getattr(settings, 'AI_PROVIDER_429_COOLDOWN_SECONDS', 300)), 1)
        cooldown_until = time.time() + cooldown_seconds
        with _provider_cooldown_lock:
            _provider_cooldown_state[provider_name] = cooldown_until

    def _parse_provider_text(self, text):
        import json

        parsed = json.loads(text)
        return {
            'risk_score': parsed.get('risk_score'),
            'urgency': parsed.get('urgency'),
            'recommended_actions': parsed.get('recommended_actions', []),
            'moderation_flags': parsed.get('moderation_flags', {}),
        }

    def _enrich_explainability(self, response, payload):
        indicators = []
        severity = payload.get('incident_severity')
        if severity and severity >= 4:
            indicators.append('Reported incident severity is critical or emergency.')

        sensor_count = len(payload.get('sensor_context', []))
        if sensor_count:
            indicators.append(f'{sensor_count} recent anomalous sensor readings were included in the assessment.')

        if payload.get('transcription'):
            indicators.append('A voice transcription was considered during triage.')

        if payload.get('location'):
            indicators.append('Location context was available for the safety review.')

        text = ' '.join([
            payload.get('title', ''),
            payload.get('description', ''),
            payload.get('transcription', ''),
        ]).lower()
        matched_keywords = []
        for keywords in self.RISK_KEYWORDS.values():
            for keyword in keywords:
                if keyword in text and keyword not in matched_keywords:
                    matched_keywords.append(keyword)
        if matched_keywords:
            indicators.append(f'Risk-related keywords were detected: {", ".join(matched_keywords[:4])}.')

        risk_score = response.get('risk_score') or 0
        urgency = response.get('urgency') or 'low'
        if risk_score >= 70:
            confidence_label = 'strong-signal'
        elif risk_score >= 40 or len(indicators) >= 2:
            confidence_label = 'moderate-signal'
        else:
            confidence_label = 'limited-signal'

        summary_parts = [f'Triage estimated {urgency} urgency']
        if risk_score:
            summary_parts.append(f'with a risk score of {risk_score}')
        if indicators:
            summary_parts.append(indicators[0].rstrip('.'))

        response['risk_indicators'] = indicators
        response['confidence_label'] = confidence_label
        response['explanation_summary'] = '. '.join(summary_parts).strip() + '.'

    def _moderation_flags(self, payload):
        text = ' '.join([
            payload.get('title', ''),
            payload.get('description', ''),
            payload.get('transcription', ''),
        ]).lower()
        return {
            'contains_phone_number': any(char.isdigit() for char in text) and len([char for char in text if char.isdigit()]) >= 7,
            'contains_email': '@' in text,
            'graphic_violence_terms': any(term in text for term in ['bleeding', 'knife', 'kill', 'weapon']),
            'provider_moderation_checked': False,
        }

    def get_recent_audits_for_user(self, user, limit=20):
        return AIAuditRecord.objects.filter(user=user).order_by('-created_at')[:limit]

    def get_incident_for_user(self, user, incident_id):
        queryset = Incident.objects.select_related('voice_recording', 'reporter')
        if user.is_staff:
            return queryset.get(id=incident_id)
        return queryset.get(id=incident_id, reporter=user)

    def chatbot_safety_tips(self, message, *, location=None, language='en'):
        language_code = 'sw' if language == 'sw' else 'en'
        text = (message or '').lower()
        matched_intents = []
        compiled_tips = []

        for rule in self.SAFETY_INTENT_RULES:
            if any(keyword in text for keyword in rule['keywords']):
                matched_intents.append(rule['intent'])
                for tip in rule['tips'][language_code]:
                    if tip not in compiled_tips:
                        compiled_tips.append(tip)

        if not compiled_tips:
            matched_intents = ['general-safety']
            if language_code == 'sw':
                compiled_tips = [
                    'Ukijihisi huna usalama, piga huduma za dharura na mjulishe mtu unayemwamini.',
                    'Hakikisha simu ina chaji na kushiriki eneo kumewashwa kwa watu unaowaamini.',
                    'Weka kumbukumbu za tukio kwa usalama pamoja na tarehe, mahali na ushahidi.',
                ]
            else:
                compiled_tips = [
                    'If you feel unsafe, contact emergency services and a trusted person immediately.',
                    'Keep your phone charged and location sharing enabled with trusted contacts.',
                    'Document incidents safely with dates, places, and any evidence available.',
                ]

        if language_code == 'sw':
            immediate_steps = [
                'Nenda sehemu salama yenye watu karibu nawe.',
                'Wasiliana na huduma za dharura kama hatari ni ya haraka.',
                'Tumia tahadhari ya dharura na shiriki eneo lako kwa watu unaowaamini.',
            ]
            reply = 'Nipo hapa kukusaidia kupanga usalama wako. Hapa kuna hatua za vitendo unazoweza kuchukua sasa.'
            disclaimer = 'Msaidizi huu unatoa mwongozo wa usalama, sio ushauri wa kisheria au kitabibu.'
            quick_replies = [
                'Ninafuatwa sasa',
                'Nahitaji vidokezo vya ushahidi',
                'Nina hofu na wasiwasi',
                'Nisaidie usalama wa simu',
            ]
            action_labels = {
                'open_emergency': 'Fungua Dharura',
                'open_incident_report': 'Ripoti Tukio',
                'call_hotline': 'Piga Namba ya Msaada',
            }
        else:
            immediate_steps = [
                'Move to a safer place with people nearby.',
                'Contact emergency services if there is immediate risk.',
                'Use your emergency alert and share your location with trusted contacts.',
            ]
            reply = 'I am here to support your safety planning. Here are practical steps you can take now.'
            disclaimer = 'This assistant provides safety guidance, not legal or medical advice.'
            quick_replies = [
                'I am being followed',
                'Need evidence tips',
                'I feel unsafe right now',
                'Help with digital safety',
            ]
            action_labels = {
                'open_emergency': 'Open Emergency',
                'open_incident_report': 'Create Incident Report',
                'call_hotline': 'Call Hotline',
            }

        hotline_number = getattr(settings, 'GBV_HOTLINE_NUMBER', '')

        return {
            'reply': reply,
            'language': language_code,
            'matched_intents': matched_intents,
            'tips': compiled_tips[:6],
            'immediate_steps': immediate_steps,
            'location_acknowledged': bool(location),
            'disclaimer': disclaimer,
            'quick_replies': quick_replies,
            'hotline_number': hotline_number,
            'action_labels': action_labels,
            'escalate_to_emergency': any(intent in matched_intents for intent in ['immediate-danger', 'stalking-or-following']),
        }

    def contact_owner_assistance(self, user, message, *, conversation_summary=''):
        from alerts.services import AlertService

        owners = self.get_owner_users().exclude(id=user.id).select_related('profile')
        alert_service = AlertService()
        primary_owner = owners.first()
        thread = AIOwnerInboxThread.objects.create(
            requester=user,
            assigned_owner=primary_owner,
            subject=f'Owner assistance request from {user.username}',
            last_message_at=timezone.now(),
            requester_last_read_at=timezone.now(),
        )
        initial_body = message.strip() or 'No message provided.'
        if conversation_summary.strip():
            initial_body = f'{initial_body}\n\nConversation summary:\n{conversation_summary.strip()}'
        initial_message = AIOwnerInboxMessage.objects.create(
            thread=thread,
            sender=user,
            sender_role='user',
            body=initial_body,
        )
        thread.last_message_at = initial_message.created_at
        thread.requester_last_read_at = initial_message.created_at
        thread.save(update_fields=['last_message_at', 'requester_last_read_at', 'updated_at'])

        payload = {
            'owners_contacted': 0,
            'sms_sent': 0,
            'push_sent': 0,
            'email_sent': 0,
            'owner_usernames': [],
            'thread_id': thread.id,
        }

        support_message = (
            f'AI owner assistance requested by {user.username}. '
            f'Message: {message.strip() or "No message provided."}'
        )
        if conversation_summary.strip():
            support_message = f'{support_message} Conversation summary: {conversation_summary.strip()}'

        for owner in owners:
            payload['owners_contacted'] += 1
            payload['owner_usernames'].append(owner.username)
            profile = getattr(owner, 'profile', None)

            if profile and profile.phone_number:
                result = alert_service.send_sms_alert(profile.phone_number, support_message)
                if result.get('success'):
                    payload['sms_sent'] += 1

            if owner.email:
                result = alert_service.send_email_alert(
                    owner.email,
                    'AI Owner Assistance Request',
                    support_message,
                )
                if result.get('success'):
                    payload['email_sent'] += 1

            if profile and profile.fcm_token:
                result = alert_service.send_push_notification(
                    profile.fcm_token,
                    'AI Owner Assistance Request',
                    support_message,
                    data={'scope': 'ai-owner-assist', 'requester': user.username},
                )
                if result.get('success'):
                    payload['push_sent'] += 1

        return payload
