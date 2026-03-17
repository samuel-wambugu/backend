from django.contrib import admin
from .models import UserProfile, SafeLocation


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'phone_number', 'emergency_mode', 'location_sharing_enabled']
    list_filter = ['emergency_mode', 'location_sharing_enabled']
    search_fields = ['user__username', 'phone_number']


@admin.register(SafeLocation)
class SafeLocationAdmin(admin.ModelAdmin):
    list_display = ['name', 'user', 'latitude', 'longitude', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'user__username', 'address']
