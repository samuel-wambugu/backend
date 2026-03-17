"""
Django settings for GBV Backend project.
"""
from pathlib import Path
import os
import json
from datetime import timedelta
from typing import cast
import dj_database_url
from decouple import config

BASE_DIR = Path(__file__).resolve().parent.parent


def _strip_wrapping_quotes(value: object) -> str:
    """Remove accidental surrounding single/double quotes from env values."""
    if not isinstance(value, str):
        return str(value)
    trimmed = value.strip()
    if len(trimmed) >= 2 and trimmed[0] == trimmed[-1] and trimmed[0] in {"'", '"'}:
        return trimmed[1:-1]
    return trimmed

SECRET_KEY = config('SECRET_KEY', default='change-this-before-production')

DEBUG = config('DEBUG', default=False, cast=bool)

from decouple import config

# Read ALLOWED_HOSTS from environment; default to empty string if not set
allowed_hosts_raw = config('ALLOWED_HOSTS', default='').strip()

if allowed_hosts_raw:
    ALLOWED_HOSTS = [host.strip() for host in allowed_hosts_raw.split(',') if host.strip()]
elif DEBUG:
    # Local mobile development often uses hosts such as 10.0.2.2 or LAN IPs.
    ALLOWED_HOSTS = ['*']
else:
    ALLOWED_HOSTS = ['127.0.0.1', 'localhost']

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third party apps
    'rest_framework',
    'corsheaders',
    'channels',
    
    # Local apps
    'users',
    'voice_recognition',
    'alerts',
    'sensors',
    'incidents',
    'ai_gateway',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'gbv_backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'gbv_backend.wsgi.application'
ASGI_APPLICATION = 'gbv_backend.asgi.application'

# Database
DATABASE_URL = cast(str, config('DATABASE_URL', default=''))
if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(
            str(DATABASE_URL),
            conn_max_age=config('DB_CONN_MAX_AGE', default=600, cast=int),
            ssl_require=not DEBUG,
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Media files
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Base URL for building absolute links (e.g. audio file URLs in alert emails/SMS).
# Set SITE_URL=https://yourserver.example.com in .env for production.
SITE_URL = config('SITE_URL', default='http://127.0.0.1:8000')

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# CORS Settings
allowed_origins_raw = config('CORS_ALLOWED_ORIGINS', default='http://localhost:3000,http://127.0.0.1:3000,http://localhost:8080')
CORS_ALLOWED_ORIGINS = [origin.strip() for origin in allowed_origins_raw.split(',') if origin.strip()]
CORS_ALLOW_ALL_ORIGINS = config('CORS_ALLOW_ALL_ORIGINS', default=False, cast=bool)

# Allow localhost dev servers that use random ports (e.g. Flutter web debug).
allowed_origin_regexes_raw = config(
    'CORS_ALLOWED_ORIGIN_REGEXES',
    default=r'^http://localhost:\d+$,^http://127\.0\.0\.1:\d+$',
)
CORS_ALLOWED_ORIGIN_REGEXES = [
    pattern.strip() for pattern in allowed_origin_regexes_raw.split(',') if pattern.strip()
]

csrf_origins_raw = config('CSRF_TRUSTED_ORIGINS', default='http://localhost:3000,http://127.0.0.1:3000')
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in csrf_origins_raw.split(',') if origin.strip()]

# REST Framework
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework_simplejwt.authentication.JWTAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=config('JWT_ACCESS_TOKEN_MINUTES', default=30, cast=int)),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=config('JWT_REFRESH_TOKEN_DAYS', default=7, cast=int)),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': False,
}

# Celery Configuration
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = config('CELERY_RESULT_BACKEND', default='redis://localhost:6379/0')

# Twilio Configuration (for SMS alerts)
SMS_PROVIDER = config('SMS_PROVIDER', default='twilio').strip().lower()

# Advanta SMS configuration
ADVANTA_SMS_API_URL = config('ADVANTA_SMS_API_URL', default='')
ADVANTA_SMS_API_KEY = config('ADVANTA_SMS_API_KEY', default='')
ADVANTA_SMS_SENDER_ID = config('ADVANTA_SMS_SENDER_ID', default='')

# Mobitech SMS configuration
MOBITECH_SMS_API_URL = config(
    'MOBITECH_SMS_API_URL',
    default='https://app.mobitechtechnologies.com/sms/sendmultiple',
)
MOBITECH_SMS_API_KEY = config('MOBITECH_SMS_API_KEY', default='')
MOBITECH_SMS_SENDER_NAME = config('MOBITECH_SMS_SENDER_NAME', default='MOBI-TECH')
MOBITECH_SMS_SERVICE_ID = config('MOBITECH_SMS_SERVICE_ID', default=0, cast=int)
MOBITECH_SMS_RESPONSE_TYPE = config('MOBITECH_SMS_RESPONSE_TYPE', default='json')

# Africa's Talking SMS configuration
AFRICASTALKING_SMS_API_URL = config(
    'AFRICASTALKING_SMS_API_URL',
    default='https://api.africastalking.com/version1/messaging',
)
AFRICASTALKING_USERNAME = config('AFRICASTALKING_USERNAME', default='')
AFRICASTALKING_API_KEY = config('AFRICASTALKING_API_KEY', default='')
AFRICASTALKING_SENDER_ID = config('AFRICASTALKING_SENDER_ID', default='')

# Twilio configuration (used for SMS and voice calls)
TWILIO_ACCOUNT_SID = config('TWILIO_ACCOUNT_SID', default='')
TWILIO_AUTH_TOKEN = config('TWILIO_AUTH_TOKEN', default='')
TWILIO_PHONE_NUMBER = config('TWILIO_PHONE_NUMBER', default='')
TWILIO_ENABLE_VOICE_CALLS = config('TWILIO_ENABLE_VOICE_CALLS', default=True, cast=bool)

# Firebase Configuration (for push notifications)
FIREBASE_CREDENTIALS_PATH = config('FIREBASE_CREDENTIALS_PATH', default='')
GBV_HOTLINE_NUMBER = config('GBV_HOTLINE_NUMBER', default='')
APP_REGISTER_URL = config('APP_REGISTER_URL', default='http://localhost:3000/register')
ALERT_DISPATCH_MODE = config('ALERT_DISPATCH_MODE', default='')

# Email Configuration
EMAIL_BACKEND = _strip_wrapping_quotes(
    str(config('EMAIL_BACKEND', default='django.core.mail.backends.smtp.EmailBackend'))
)
DEFAULT_FROM_EMAIL = _strip_wrapping_quotes(str(config('DEFAULT_FROM_EMAIL', default='webmaster@localhost')))
EMAIL_HOST = _strip_wrapping_quotes(str(config('EMAIL_HOST', default='localhost')))
EMAIL_PORT = config('EMAIL_PORT', default=25, cast=int)
EMAIL_HOST_USER = _strip_wrapping_quotes(str(config('EMAIL_HOST_USER', default='')))
EMAIL_HOST_PASSWORD = _strip_wrapping_quotes(str(config('EMAIL_HOST_PASSWORD', default='')))
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=False, cast=bool)
EMAIL_USE_SSL = config('EMAIL_USE_SSL', default=False, cast=bool)
AUTH_OTP_ALLOW_DEBUG_FALLBACK = config('AUTH_OTP_ALLOW_DEBUG_FALLBACK', default=DEBUG, cast=bool)

# Voice Recognition Settings
VOICE_RECOGNITION_MODEL = 'base'  # Can be: tiny, base, small, medium, large
AUDIO_UPLOAD_PATH = 'audio_recordings/'

# Upload limits
MAX_EVIDENCE_FILE_SIZE_MB = config('MAX_EVIDENCE_FILE_SIZE_MB', default=20, cast=int)

# Security settings (production-safe defaults)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=not DEBUG, cast=bool)

# AI provider settings (for upcoming API integrations)
AI_PROVIDER = config('AI_PROVIDER', default='none')
AI_API_BASE_URL = config('AI_API_BASE_URL', default='')
AI_API_KEY = config('AI_API_KEY', default='')
AI_MODEL = config('AI_MODEL', default='')
AI_OPENAI_API_BASE_URL = config('AI_OPENAI_API_BASE_URL', default='https://api.openai.com')
AI_OPENAI_API_KEY = config('AI_OPENAI_API_KEY', default=AI_API_KEY)
AI_OPENAI_MODEL = config('AI_OPENAI_MODEL', default=AI_MODEL)
AI_AZURE_OPENAI_ENDPOINT = config('AI_AZURE_OPENAI_ENDPOINT', default='')
AI_AZURE_OPENAI_API_KEY = config('AI_AZURE_OPENAI_API_KEY', default='')
AI_AZURE_OPENAI_DEPLOYMENT = config('AI_AZURE_OPENAI_DEPLOYMENT', default='')
AI_AZURE_OPENAI_API_VERSION = config('AI_AZURE_OPENAI_API_VERSION', default='2024-10-21')
AI_ANTHROPIC_API_BASE_URL = config('AI_ANTHROPIC_API_BASE_URL', default='https://api.anthropic.com')
AI_ANTHROPIC_API_KEY = config('AI_ANTHROPIC_API_KEY', default='')
AI_ANTHROPIC_MODEL = config('AI_ANTHROPIC_MODEL', default='')
AI_ANTHROPIC_VERSION = config('AI_ANTHROPIC_VERSION', default='2023-06-01')
AI_PROVIDER_FAILOVER_ORDER = [
    item.strip() for item in config('AI_PROVIDER_FAILOVER_ORDER', default='').split(',') if item.strip()
]
AI_PROVIDER_429_MAX_RETRIES = config('AI_PROVIDER_429_MAX_RETRIES', default=2, cast=int)
AI_PROVIDER_429_BACKOFF_BASE_SECONDS = config('AI_PROVIDER_429_BACKOFF_BASE_SECONDS', default=0.8, cast=float)
AI_PROVIDER_429_JITTER_SECONDS = config('AI_PROVIDER_429_JITTER_SECONDS', default=0.6, cast=float)
AI_PROVIDER_429_COOLDOWN_SECONDS = config('AI_PROVIDER_429_COOLDOWN_SECONDS', default=300, cast=int)
AI_PROVIDER_SKIP_UNCONFIGURED = config('AI_PROVIDER_SKIP_UNCONFIGURED', default=True, cast=bool)
AI_OWNER_USERNAMES = [
    item.strip() for item in config('AI_OWNER_USERNAMES', default='').split(',') if item.strip()
]
authority_alert_contacts_raw = config('AUTHORITY_ALERT_CONTACTS', default='')
authority_alert_contacts_text = (
    authority_alert_contacts_raw
    if isinstance(authority_alert_contacts_raw, str)
    else str(authority_alert_contacts_raw)
)
try:
    AUTHORITY_ALERT_CONTACTS = (
        json.loads(authority_alert_contacts_text)
        if authority_alert_contacts_text.strip()
        else []
    )
except json.JSONDecodeError:
    AUTHORITY_ALERT_CONTACTS = []

# Structured logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s %(levelname)s %(name)s %(message)s'
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': config('LOG_LEVEL', default='INFO'),
    },
}
