from rest_framework import serializers
from django.contrib.auth.models import User
from django.conf import settings
from .models import UserProfile, SafeLocation


class UserProfileSerializer(serializers.ModelSerializer):
    """Serializer for user profile."""
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.EmailField(source='user.email', read_only=True)
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    is_owner = serializers.SerializerMethodField()
    is_staff = serializers.BooleanField(source='user.is_staff', read_only=True)

    def get_is_owner(self, obj):
        owner_usernames = set(getattr(settings, 'AI_OWNER_USERNAMES', []))
        return bool(obj.user.is_superuser or obj.user.username in owner_usernames)
    
    class Meta:
        model = UserProfile
        fields = [
            'id', 'user_id', 'username', 'email', 'phone_number',
            'date_of_birth', 'address', 'emergency_mode',
            'fcm_token', 'location_sharing_enabled', 'is_owner', 'is_staff', 'created_at'
        ]


class UserRegistrationSerializer(serializers.ModelSerializer):
    """Serializer for user registration."""
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)
    phone_number = serializers.CharField(required=False)
    
    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password_confirm', 'phone_number']
    
    def validate(self, data):
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError("Passwords do not match")
        return data
    
    def create(self, validated_data):
        validated_data.pop('password_confirm')
        phone_number = validated_data.pop('phone_number', '')
        
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password']
        )
        
        profile, _ = UserProfile.objects.get_or_create(user=user)
        if phone_number:
            profile.phone_number = phone_number
            profile.save(update_fields=['phone_number'])
        
        return user


class LoginOTPRequestSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()


class LoginOTPVerifySerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()
    otp = serializers.RegexField(r'^\d{6}$', error_messages={
        'invalid': 'OTP must be a 6-digit code.',
    })


class LoginOTPResendSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()


class SafeLocationSerializer(serializers.ModelSerializer):
    """Serializer for safe locations."""
    
    class Meta:
        model = SafeLocation
        fields = [
            'id', 'name', 'address', 'latitude', 'longitude',
            'radius', 'is_active', 'created_at'
        ]
