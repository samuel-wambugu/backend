from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('alerts', '0002_livesafetysession_and_alert_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='emergencycontact',
            name='is_trusted_circle',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='livesafetysession',
            name='trusted_contacts',
            field=models.ManyToManyField(blank=True, related_name='live_sessions', to='alerts.emergencycontact'),
        ),
    ]
