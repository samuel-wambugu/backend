"""
WSGI config for GBV Backend project.
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'gbv_backend.settings')

application = get_wsgi_application()
