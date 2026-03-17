from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('alerts', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='LiveSafetySession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=120)),
                ('note', models.TextField(blank=True)),
                ('destination', models.CharField(blank=True, max_length=255)),
                ('check_in_interval_minutes', models.PositiveIntegerField(default=15)),
                ('started_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField()),
                ('last_ping_at', models.DateTimeField(blank=True, null=True)),
                ('current_location', models.JSONField(blank=True, null=True)),
                ('status', models.CharField(choices=[('active', 'Active'), ('completed', 'Completed'), ('cancelled', 'Cancelled'), ('escalated', 'Escalated')], default='active', max_length=20)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('escalated_alert', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='originating_live_sessions', to='alerts.alert')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='live_safety_sessions', to='auth.user')),
            ],
            options={
                'ordering': ['-started_at', '-updated_at'],
            },
        ),
        migrations.AlterField(
            model_name='alert',
            name='alert_type',
            field=models.CharField(choices=[('voice', 'Voice Emergency'), ('sensor', 'Sensor Triggered'), ('manual', 'Manual Activation'), ('location', 'Unsafe Location'), ('checkin_missed', 'Missed Safe Check-In'), ('live_session_missed', 'Missed Live Safety Session')], max_length=20),
        ),
    ]