import speech_recognition as sr
import whisper
import json
import logging
from functools import lru_cache
from pydub import AudioSegment
from django.conf import settings
from .models import VoiceRecording, EmergencyKeyword
import os


logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_whisper_model(model_name):
    """Cache model in worker memory to avoid reloading for every request."""
    return whisper.load_model(model_name)


class VoiceRecognitionService:
    """Service for processing voice recordings with AI."""
    
    def __init__(self):
        # Load Whisper model for accurate transcription
        self.whisper_model = _get_whisper_model(settings.VOICE_RECOGNITION_MODEL)
        self.recognizer = sr.Recognizer()
        
    def transcribe_audio(self, audio_file_path, language='en'):
        """
        Transcribe audio file using Whisper AI.
        
        Args:
            audio_file_path: Path to audio file
            language: Language code (default: 'en')
            
        Returns:
            dict: Transcription result with text and confidence
        """
        try:
            # Load and transcribe with Whisper
            result = self.whisper_model.transcribe(
                audio_file_path,
                language=language,
                fp16=False
            )
            
            return {
                'text': result['text'],
                'language': result.get('language', language),
                'segments': result.get('segments', []),
                'confidence': self._calculate_confidence(result)
            }
        except Exception as e:
            logger.exception("audio_transcription_failed", extra={'error': str(e), 'audio_file_path': audio_file_path})
            return None
    
    def detect_emergency_keywords(self, text, language='en'):
        """
        Detect emergency keywords in transcribed text.
        
        Args:
            text: Transcribed text
            language: Language code
            
        Returns:
            dict: Emergency detection results
        """
        keywords = EmergencyKeyword.objects.filter(
            is_active=True,
            language=language
        )
        
        detected = []
        max_severity = 0
        text_lower = text.lower()
        
        for keyword in keywords:
            if keyword.keyword.lower() in text_lower:
                detected.append({
                    'keyword': keyword.keyword,
                    'severity': keyword.severity
                })
                max_severity = max(max_severity, keyword.severity)
        
        is_emergency = len(detected) > 0 and max_severity >= 3
        
        return {
            'is_emergency': is_emergency,
            'detected_keywords': detected,
            'max_severity': max_severity
        }
    
    def process_recording(self, recording_id):
        """
        Process a voice recording: transcribe and analyze.
        
        Args:
            recording_id: ID of VoiceRecording instance
            
        Returns:
            bool: Success status
        """
        try:
            recording = VoiceRecording.objects.get(id=recording_id)
            
            # Transcribe audio
            result = self.transcribe_audio(
                recording.audio_file.path,
                recording.language
            )
            
            if result:
                recording.transcription = result['text']
                recording.confidence_score = result['confidence']
                
                # Detect emergency keywords
                emergency_check = self.detect_emergency_keywords(
                    result['text'],
                    recording.language
                )
                
                recording.is_emergency = emergency_check['is_emergency']
                recording.keywords_detected = emergency_check['detected_keywords']
                recording.processed = True
                recording.save()
                
                # If emergency detected, trigger alert
                if recording.is_emergency:
                    from alerts.models import Alert
                    from alerts.services import AlertService
                    preview = (result['text'] or '').strip()[:200]
                    alert_priority = emergency_check['max_severity']
                    if alert_priority < 3:
                        alert_priority = 3
                    alert = Alert.objects.create(
                        user=recording.user,
                        alert_type='voice',
                        priority=alert_priority,
                        message=f"Emergency detected from voice recording: {preview}",
                        location=recording.location,
                        voice_recording=recording,
                    )
                    AlertService().send_emergency_alert(alert.id)
                
                return True
            
            return False
            
        except Exception as e:
            logger.exception("voice_recording_processing_failed", extra={'recording_id': recording_id, 'error': str(e)})
            return False
    
    def _calculate_confidence(self, result):
        """Calculate average confidence from Whisper segments."""
        segments = result.get('segments', [])
        if not segments:
            return 0.0
        
        # Whisper doesn't provide confidence, estimate from segment data
        total_prob = sum(
            segment.get('avg_logprob', 0) for segment in segments
        )
        return min(max((total_prob / len(segments) + 1) * 50, 0), 100)
