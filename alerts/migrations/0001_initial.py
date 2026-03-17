from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('sensors', '__first__'),
        ('voice_recognition', '__first__'),
    ]

    operations = [
        migrations.CreateModel(
            name='Alert',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('alert_type', models.CharField(choices=[('voice', 'Voice Emergency'), ('sensor', 'Sensor Triggered'), ('manual', 'Manual Activation'), ('location', 'Unsafe Location'), ('checkin_missed', 'Missed Safe Check-In')], max_length=20)),
                ('message', models.TextField()),
                ('location', models.JSONField(blank=True, null=True)),
                ('status', models.CharField(choices=[('pending', 'Pending'), ('sent', 'Sent'), ('delivered', 'Delivered'), ('failed', 'Failed')], default='pending', max_length=20)),
                ('priority', models.IntegerField(default=1)),
                ('sms_sent', models.BooleanField(default=False)),
                ('push_sent', models.BooleanField(default=False)),
                ('email_sent', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('sensor_reading', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='sensors.sensorreading')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='alerts', to=settings.AUTH_USER_MODEL)),
                ('voice_recording', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='voice_recognition.voicerecording')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='EmergencyContact',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('phone_number', models.CharField(max_length=20)),
                ('email', models.EmailField(blank=True, max_length=254)),
                ('relationship', models.CharField(max_length=50)),
                ('is_primary', models.BooleanField(default=False)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='emergency_contacts', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-is_primary', 'name']},
        ),
        migrations.CreateModel(
            name='AlertLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('channel', models.CharField(max_length=20)),
                ('status', models.CharField(max_length=20)),
                ('response', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('alert', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='logs', to='alerts.alert')),
                ('contact', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='alerts.emergencycontact')),
            ],
        ),
        migrations.CreateModel(
            name='SafeCheckIn',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=120)),
                ('note', models.TextField(blank=True)),
                ('scheduled_for', models.DateTimeField()),
                ('grace_minutes', models.PositiveIntegerField(default=10)),
                ('status', models.CharField(choices=[('scheduled', 'Scheduled'), ('completed', 'Completed'), ('missed', 'Missed'), ('cancelled', 'Cancelled')], default='scheduled', max_length=20)),
                ('location_snapshot', models.JSONField(blank=True, null=True)),
                ('destination', models.CharField(blank=True, max_length=255)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('missed_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('escalated_alert', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='originating_checkins', to='alerts.alert')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='safe_checkins', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-scheduled_for', '-created_at']},
        ),
    ]
