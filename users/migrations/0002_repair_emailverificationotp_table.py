from django.db import migrations


def create_email_otp_table_if_missing(apps, schema_editor):
    EmailVerificationOTP = apps.get_model('users', 'EmailVerificationOTP')
    table_name = EmailVerificationOTP._meta.db_table

    existing_tables = set(schema_editor.connection.introspection.table_names())
    if table_name in existing_tables:
        return

    schema_editor.create_model(EmailVerificationOTP)


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(
            create_email_otp_table_if_missing,
            migrations.RunPython.noop,
        ),
    ]
