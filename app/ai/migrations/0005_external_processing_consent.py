import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ai", "0004_alter_modelbudgetreservation_state_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="modelconfig",
            name="connection_route",
            field=models.CharField(blank=True, choices=[("direct", "直连供应商"),
                ("gateway", "通过网关"), ("unknown", "链路未知")], max_length=16, null=True),
        ),
        migrations.AddField(
            model_name="modelconfig",
            name="known_upstream_providers",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="modelconfig",
            name="outbound_confirmation_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="modelconfig",
            name="outbound_confirmation_by",
            field=models.ForeignKey(blank=True, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="confirmed_ai_model_configs", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="modelconfig",
            name="retention_description",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="modelconfig",
            name="retention_state",
            field=models.CharField(blank=True, choices=[("known", "已知"), ("unknown", "未知")],
                max_length=8, null=True),
        ),
        migrations.AddField(
            model_name="modelconfig",
            name="upstream_state",
            field=models.CharField(blank=True, choices=[("known", "已知"), ("unknown", "未知")],
                max_length=8, null=True),
        ),
        migrations.AddConstraint(
            model_name="modelconfig",
            constraint=models.CheckConstraint(condition=(models.Q(("connection_route__isnull", True)) |
                models.Q(("connection_route__in", ("direct", "gateway", "unknown")))),
                name="ai_modelconfig_route_valid"),
        ),
        migrations.AddConstraint(
            model_name="modelconfig",
            constraint=models.CheckConstraint(condition=(
                models.Q(("upstream_state__isnull", True)) |
                (models.Q(("upstream_state", "unknown")) &
                    (models.Q(("known_upstream_providers__isnull", True)) |
                     models.Q(("known_upstream_providers", "")))) |
                (models.Q(("upstream_state", "known")) &
                    models.Q(("known_upstream_providers__gt", "")))),
                name="ai_modelconfig_upstream_valid"),
        ),
        migrations.AddConstraint(
            model_name="modelconfig",
            constraint=models.CheckConstraint(condition=(
                models.Q(("retention_state__isnull", True)) |
                (models.Q(("retention_state", "unknown")) &
                    (models.Q(("retention_description__isnull", True)) |
                     models.Q(("retention_description", "")))) |
                (models.Q(("retention_state", "known")) &
                    models.Q(("retention_description__gt", "")))),
                name="ai_modelconfig_retention_valid"),
        ),
        migrations.AddConstraint(
            model_name="modelconfig",
            constraint=models.CheckConstraint(condition=(
                models.Q(("outbound_confirmation_at__isnull", True),
                    ("outbound_confirmation_by__isnull", True)) |
                models.Q(("outbound_confirmation_at__isnull", False),
                    ("outbound_confirmation_by__isnull", False))),
                name="ai_modelconfig_confirmation_pair"),
        ),
    ]
