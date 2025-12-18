from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("tracker", "0002_userpreference_is_onboarded"),
    ]

    operations = [
        migrations.AlterField(
            model_name="userpreference",
            name="inflation_baseline_mode",
            field=models.CharField(
                choices=[
                    ("GLOBAL", "Whole history"),
                    ("PER_EMPLOYER", "Current employer only"),
                    ("LAST_INCREASE", "Last salary increase"),
                    ("MANUAL", "Manual selection"),
                ],
                default="GLOBAL",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="userpreference",
            name="inflation_manual_entry",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="tracker.salaryentry",
            ),
        ),
    ]
