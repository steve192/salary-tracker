# Generated fresh initial migration after reset
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Employer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="employers", to="accounts.user")),
            ],
            options={
                "ordering": ["name"],
                "unique_together": {("user", "name")},
            },
        ),
        migrations.CreateModel(
            name="InflationSource",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(choices=[("ECB_DE", "Germany (ECB)")], max_length=20, unique=True)),
                ("label", models.CharField(max_length=100)),
                ("description", models.CharField(blank=True, max_length=255)),
                ("is_active", models.BooleanField(default=True)),
                ("available_to_users", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["label"],
            },
        ),
        migrations.CreateModel(
            name="SalaryEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("effective_date", models.DateField()),
                ("end_date", models.DateField(blank=True, null=True)),
                ("entry_type", models.CharField(choices=[("REGULAR", "Regular"), ("BONUS", "Bonus")], default="REGULAR", max_length=10)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("employer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="salary_entries", to="tracker.employer")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="salary_entries", to="accounts.user")),
            ],
            options={
                "ordering": ["-effective_date", "-created_at"],
            },
        ),
        migrations.CreateModel(
            name="UserPreference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("currency", models.CharField(choices=[("USD", "USD"), ("EUR", "EUR"), ("GBP", "GBP"), ("CHF", "CHF"), ("CAD", "CAD")], default="USD", max_length=3)),
                ("inflation_baseline_mode", models.CharField(choices=[("GLOBAL", "Whole history"), ("PER_EMPLOYER", "Current employer only")], default="GLOBAL", max_length=20)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="preferences", to="accounts.user")),
                ("inflation_source", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="user_preferences", to="tracker.inflationsource")),
            ],
        ),
        migrations.CreateModel(
            name="InflationRate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("period", models.DateField(help_text="Month this rate applies to (1st of month)")),
                ("index_value", models.DecimalField(decimal_places=4, max_digits=10)),
                ("metadata", models.JSONField(blank=True, default=dict)),
                ("fetched_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("source", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rates", to="tracker.inflationsource")),
            ],
            options={
                "ordering": ["-period"],
                "unique_together": {("source", "period")},
            },
        ),
    ]
