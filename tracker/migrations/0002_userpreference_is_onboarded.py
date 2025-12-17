from django.db import migrations, models


def mark_existing_onboarded(apps, schema_editor):
    UserPreference = apps.get_model("tracker", "UserPreference")
    UserPreference.objects.update(is_onboarded=True)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="userpreference",
            name="is_onboarded",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(mark_existing_onboarded, noop),
    ]
