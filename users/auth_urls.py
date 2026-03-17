from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import login_request_otp, verify_login_otp, resend_login_otp

urlpatterns = [
    path('login/', login_request_otp, name='login_request_otp'),
    path('login/verify-otp/', verify_login_otp, name='verify_login_otp'),
    path('login/resend-otp/', resend_login_otp, name='resend_login_otp'),
    path('refresh/', TokenRefreshView.as_view(), name='token_refresh'),
]
