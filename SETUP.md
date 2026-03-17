# Backend Setup Instructions

## Prerequisites
- Python 3.8+
- PostgreSQL (optional, SQLite is default)
- Redis

## Installation Steps

1. Create virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment:
```bash
cp .env.example .env
# Edit .env with your credentials
```

4. Run migrations:
```bash
python manage.py migrate
```

5. Create superuser:
```bash
python manage.py createsuperuser
```

6. Load initial data (optional):
```bash
python manage.py loaddata emergency_keywords
```

7. Start server:
```bash
python manage.py runserver
```

8. Start Celery (in separate terminal):
```bash
celery -A gbv_backend worker -l info
```

## Configuration

### Twilio Setup (Primary)
1. Sign up at https://www.twilio.com
2. Get Account SID, Auth Token, and a Twilio phone number.
3. Add to `.env`:
```
SMS_PROVIDER=twilio
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
TWILIO_PHONE_NUMBER=your_number
TWILIO_ENABLE_VOICE_CALLS=true
# Optional: force immediate alert dispatch in API process (useful in local dev)
# ALERT_DISPATCH_MODE=sync
```

### Advanta SMS Setup (Optional)
If you want to use Advanta instead of Twilio for SMS later, configure:
```
SMS_PROVIDER=advanta
ADVANTA_SMS_API_URL=https://your-advanta-endpoint.example.com/sms/send
ADVANTA_SMS_API_KEY=your_advanta_api_key
ADVANTA_SMS_SENDER_ID=GBVAlert
```

### Mobitech SMS Setup (Optional)
If you want to use Mobitech bulk messaging for SMS alerts, configure:
```
SMS_PROVIDER=mobitech
MOBITECH_SMS_API_URL=https://app.mobitechtechnologies.com/sms/sendmultiple
MOBITECH_SMS_API_KEY=your_mobitech_api_key
MOBITECH_SMS_SENDER_NAME=MOBI-TECH
MOBITECH_SMS_SERVICE_ID=0
MOBITECH_SMS_RESPONSE_TYPE=json
```

The backend sends JSON in this format per recipient:
```json
{
	"mobile": "+254712244243",
	"response_type": "json",
	"sender_name": "MOBI-TECH",
	"service_id": 0,
	"message": "Emergency alert text"
}
```

Note: because Mobitech authentication header naming is not fully documented here,
the backend sends the API key in `Authorization: Bearer ...`, `X-API-KEY`, and
`h_api_key` headers for compatibility with common API gateway patterns.

### Firebase Setup
1. Create project at https://firebase.google.com
2. Download service account JSON
3. Add path to .env:
```
FIREBASE_CREDENTIALS_PATH=/path/to/credentials.json
```
4. Add real owner usernames and authority contacts to `.env`:
```
AI_OWNER_USERNAMES=admin,safety_owner_1
AUTHORITY_ALERT_CONTACTS=[{"name":"Central Police Station","phone_number":"+254700000100"}]
```
5. Make sure each owner account has a valid phone number, email, and FCM token in its user profile so SMS, email, and push fan-out can deliver.

## API Documentation

Visit `/api/docs/` after starting the server for interactive API documentation.

## Admin Panel

Access admin panel at `/admin/` using superuser credentials.
