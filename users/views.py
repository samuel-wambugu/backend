from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from django.core.mail import send_mail
from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta
import secrets
import logging
from rest_framework_simplejwt.tokens import RefreshToken
from alerts.models import EmergencyContact
from .models import UserProfile, SafeLocation, EmailVerificationOTP
from .serializers import (
    UserProfileSerializer,
    UserRegistrationSerializer,
    SafeLocationSerializer,
    LoginOTPRequestSerializer,
    LoginOTPVerifySerializer,
    LoginOTPResendSerializer,
)


logger = logging.getLogger(__name__)


OTP_EXPIRY_MINUTES = 10


def _issue_login_otp(user):
    code = f"{secrets.randbelow(10**6):06d}"
    expires_at = timezone.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)

    EmailVerificationOTP.objects.create(
        user=user,
        purpose='login',
        code=code,
        expires_at=expires_at,
    )

    try:
        send_mail(
            'Your GBV Safety email verification code',
            (
                f'Hello {user.username},\n\n'
                f'Your verification code is: {code}\n\n'
                f'This code expires in {OTP_EXPIRY_MINUTES} minutes.\n\n'
                'If you did not create this account, ignore this email.'
            ),
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
        return {'delivered': True, 'code': code}
    except Exception as exc:
        logger.warning('login_email_otp_send_failed', extra={'user_id': user.id, 'error': str(exc)})
        return {'delivered': False, 'code': code, 'error': str(exc)}


@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """Register a new user."""
    serializer = UserRegistrationSerializer(data=request.data)
    
    if serializer.is_valid():
        user = serializer.save()

        # Preserve existing behavior: if this user was pre-added as an
        # emergency contact, activate that contact record on registration.
        phone_number = ''
        profile = getattr(user, 'profile', None)
        if profile is not None:
            phone_number = (profile.phone_number or '').strip()

        matcher = Q()
        if user.email:
            matcher |= Q(email__iexact=user.email)
        if phone_number:
            matcher |= Q(phone_number=phone_number)
        if matcher:
            EmergencyContact.objects.filter(matcher).update(is_active=True)

        try:
            send_mail(
                'Welcome to GBV Safety App',
                (
                    f'Hello {user.username},\n\n'
                    'Your account has been created successfully. '
                    'You can now log in and configure your emergency contacts and safety settings.\n\n'
                    'Stay safe,\nGBV Safety App Team'
                ),
                settings.DEFAULT_FROM_EMAIL,
                [user.email],
                fail_silently=False,
            )
        except Exception as exc:
            logger.warning(
                'registration_welcome_email_failed',
                extra={'user_id': user.id, 'error': str(exc)},
            )

        return Response({
            'status': 'success',
            'message': 'User registered successfully',
            'user_id': user.id,
            'username': user.username,
        }, status=status.HTTP_201_CREATED)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['POST'])
@permission_classes([AllowAny])
def login_request_otp(request):
    """Validate username/password and send login OTP via email."""
    serializer = LoginOTPRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    username = serializer.validated_data['username'].strip()
    password = serializer.validated_data['password']
    user = authenticate(request, username=username, password=password)
    if user is None:
        return Response({'detail': 'Invalid credentials.'}, status=status.HTTP_401_UNAUTHORIZED)

    otp_result = _issue_login_otp(user)
    fallback_allowed = bool(getattr(settings, 'AUTH_OTP_ALLOW_DEBUG_FALLBACK', False))
    if not otp_result.get('delivered') and not fallback_allowed:
        return Response(
            {'detail': 'Failed to send OTP. Please try again shortly.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    response_payload = {
        'status': 'otp_sent' if otp_result.get('delivered') else 'otp_generated',
        'message': (
            'OTP sent to your email.'
            if otp_result.get('delivered')
            else 'OTP generated. Email delivery failed in this environment; use debug OTP.'
        ),
        'email': user.email,
    }
    if not otp_result.get('delivered') and fallback_allowed:
        debug_code = otp_result.get('code')
        if isinstance(debug_code, str) and debug_code:
            response_payload['debug_otp'] = debug_code

    return Response(response_payload, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def verify_login_otp(request):
    """Verify login OTP and issue JWT access/refresh tokens."""
    serializer = LoginOTPVerifySerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    username = serializer.validated_data['username'].strip()
    password = serializer.validated_data['password']
    otp = serializer.validated_data['otp'].strip()

    user = authenticate(request, username=username, password=password)
    if user is None:
        return Response({'detail': 'Invalid credentials.'}, status=status.HTTP_401_UNAUTHORIZED)

    latest_otp = (
        EmailVerificationOTP.objects
        .filter(user=user, purpose='login', used_at__isnull=True)
        .order_by('-created_at')
        .first()
    )
    if latest_otp is None:
        return Response({'detail': 'No OTP found. Request a new OTP.'}, status=status.HTTP_400_BAD_REQUEST)

    if latest_otp.expires_at < timezone.now():
        return Response({'detail': 'OTP has expired. Request a new OTP.'}, status=status.HTTP_400_BAD_REQUEST)

    if latest_otp.code != otp:
        return Response({'detail': 'Invalid OTP.'}, status=status.HTTP_400_BAD_REQUEST)

    latest_otp.used_at = timezone.now()
    latest_otp.save(update_fields=['used_at'])

    refresh = RefreshToken.for_user(user)

    return Response(
        {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def resend_login_otp(request):
    """Resend login OTP after re-validating credentials."""
    serializer = LoginOTPResendSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    username = serializer.validated_data['username'].strip()
    password = serializer.validated_data['password']
    user = authenticate(request, username=username, password=password)
    if user is None:
        return Response({'detail': 'Invalid credentials.'}, status=status.HTTP_401_UNAUTHORIZED)

    otp_result = _issue_login_otp(user)
    fallback_allowed = bool(getattr(settings, 'AUTH_OTP_ALLOW_DEBUG_FALLBACK', False))
    if not otp_result.get('delivered') and not fallback_allowed:
        return Response(
            {'detail': 'Failed to resend OTP. Please try again shortly.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    payload = {
        'detail': (
            'A new OTP has been sent to your email address.'
            if otp_result.get('delivered')
            else 'A new OTP was generated. Email delivery failed in this environment; use debug OTP.'
        )
    }
    if not otp_result.get('delivered') and fallback_allowed:
        debug_code = otp_result.get('code')
        if isinstance(debug_code, str) and debug_code:
            payload['debug_otp'] = debug_code

    return Response(payload)


class UserProfileViewSet(viewsets.ModelViewSet):
    """ViewSet for user profiles."""
    queryset = UserProfile.objects.all()
    serializer_class = UserProfileSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filter to current user's profile only."""
        return self.queryset.filter(user=self.request.user)
    
    @action(detail=False, methods=['get'])
    def me(self, request):
        """Get current user's profile."""
        profile = UserProfile.objects.get(user=request.user)
        serializer = self.get_serializer(profile)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def toggle_emergency(self, request):
        """Toggle emergency mode."""
        profile = UserProfile.objects.get(user=request.user)
        profile.emergency_mode = not profile.emergency_mode
        profile.save()
        
        return Response({
            'status': 'emergency_mode_on' if profile.emergency_mode else 'emergency_mode_off',
            'emergency_mode': profile.emergency_mode
        })
    
    @action(detail=False, methods=['post'])
    def update_fcm_token(self, request):
        """Update FCM token for push notifications."""
        profile = UserProfile.objects.get(user=request.user)
        token = request.data.get('fcm_token')
        
        if token:
            profile.fcm_token = token
            profile.save()
            return Response({'status': 'success', 'message': 'FCM token updated'})
        
        return Response({'error': 'FCM token required'}, status=status.HTTP_400_BAD_REQUEST)


class SafeLocationViewSet(viewsets.ModelViewSet):
    """ViewSet for safe locations."""
    queryset = SafeLocation.objects.all()
    serializer_class = SafeLocationSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filter to current user's locations."""
        return self.queryset.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        """Create safe location for current user."""
        serializer.save(user=self.request.user)
