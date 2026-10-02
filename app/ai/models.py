"""Append-only provider settings and auditable, household-scoped model runs."""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from app.persistence.models import EntityRecord, Household, RevisionRecord


class ModelConfig(models.Model):
    class OutboundScope(models.TextChoices):
        REVIEWED_TEXT = "reviewed_text", "仅外发已选的已发布文字"
        SELECTED_REGIONS = "selected_regions", "已选文字及主动选择的图像区域"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    household = models.ForeignKey(Household, on_delete=models.PROTECT, related_name="ai_model_configs")
    revision_no = models.PositiveIntegerField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="created_ai_model_configs")
    provider_label = models.CharField(max_length=120)
    base_url = models.URLField(max_length=500)
    model = models.CharField(max_length=160)
    cloud_enabled = models.BooleanField(default=False)
    outbound_scope = models.CharField(max_length=24, choices=OutboundScope.choices,
        default=OutboundScope.REVIEWED_TEXT)
    timeout_seconds = models.PositiveSmallIntegerField(default=30)
    max_output_tokens = models.PositiveSmallIntegerField(default=1000)
    max_input_chars = models.PositiveSmallIntegerField(default=16000)
    max_calls = models.PositiveSmallIntegerField(default=4)
    batch_budget = models.DecimalField(max_digits=14, decimal_places=6, default=0)
    input_price_per_million = models.DecimalField(max_digits=14, decimal_places=6, default=0)
    output_price_per_million = models.DecimalField(max_digits=14, decimal_places=6, default=0)
    reserved_per_call = models.DecimalField(max_digits=14, decimal_places=6, default=0)
    non_billable_gateway = models.BooleanField(default=False)
    currency = models.CharField(max_length=3, default="USD", editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_modelconfig"
        ordering = ("household_id", "revision_no")
        constraints = [
            models.UniqueConstraint(fields=("household", "revision_no"), name="ai_modelconfig_version"),
            models.CheckConstraint(condition=models.Q(revision_no__gt=0), name="ai_modelconfig_version_positive"),
            models.CheckConstraint(condition=models.Q(timeout_seconds__gte=1, timeout_seconds__lte=60),
                name="ai_modelconfig_timeout_bound"),
            models.CheckConstraint(condition=models.Q(max_output_tokens__gte=1, max_output_tokens__lte=2000),
                name="ai_modelconfig_output_bound"),
            models.CheckConstraint(condition=models.Q(max_input_chars__gte=1, max_input_chars__lte=16000),
                name="ai_modelconfig_input_bound"),
            models.CheckConstraint(condition=models.Q(max_calls__gte=1, max_calls__lte=4),
                name="ai_modelconfig_calls_bound"),
            models.CheckConstraint(condition=models.Q(batch_budget__gte=0), name="ai_modelconfig_budget_nonnegative"),
            models.CheckConstraint(condition=models.Q(input_price_per_million__gte=0),
                name="ai_modelconfig_input_price_nonnegative"),
            models.CheckConstraint(condition=models.Q(output_price_per_million__gte=0),
                name="ai_modelconfig_output_price_nonnegative"),
            models.CheckConstraint(condition=models.Q(reserved_per_call__gte=0),
                name="ai_modelconfig_reserve_nonnegative"),
            models.CheckConstraint(condition=models.Q(outbound_scope__in=("reviewed_text", "selected_regions")),
                name="ai_modelconfig_scope_valid"),
            models.CheckConstraint(condition=models.Q(currency="USD"), name="ai_modelconfig_currency_fixed"),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Model configuration versions are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Model configuration versions are retained.")


class ModelRun(models.Model):
    class TaskKind(models.TextChoices):
        QUESTION = "question", "题干识别草稿"
        KNOWLEDGE = "knowledge", "知识草稿"
        ASSESSMENT = "assessment", "作答评价草稿"
        VARIANT = "variant", "变式题草稿"

    class Status(models.TextChoices):
        QUEUED = "queued", "排队中"
        RUNNING = "running", "运行中"
        AWAITING_REVIEW = "awaiting_review", "待人工复核"
        FAILED = "failed", "失败"
        CANCELLED = "cancelled", "已取消"
        STALE = "stale", "已过期"
        APPLIED = "applied", "已应用"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    household = models.ForeignKey(Household, on_delete=models.PROTECT, related_name="ai_model_runs")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="ai_model_runs")
    config = models.ForeignKey(ModelConfig, on_delete=models.PROTECT, related_name="runs")
    config_snapshot = models.JSONField()
    task_kind = models.CharField(max_length=16, choices=TaskKind.choices)
    question_revision_ids = models.JSONField(default=list)
    attempt_revision = models.ForeignKey(RevisionRecord, null=True, blank=True,
        on_delete=models.PROTECT, related_name="ai_model_runs")
    source_revision_ids = models.JSONField(default=list)
    selected_region_revision_ids = models.JSONField(default=list)
    include_attempt_text = models.BooleanField(default=False)
    expected_heads = models.JSONField(default=list)
    expected_dependencies = models.JSONField(default=list)
    review_pointers = models.JSONField(default=list)
    prompt_version = models.CharField(max_length=40, default="study-workbench.ai.prompt.v1")
    schema_version = models.CharField(max_length=48, default="study-workbench.ai.v1")
    request_key = models.CharField(max_length=160)
    fingerprint = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    execution_requested_at = models.DateTimeField(null=True, blank=True)
    response = models.JSONField(null=True, blank=True)
    tool_results = models.JSONField(default=list)
    usage = models.JSONField(default=dict)
    estimated_cost = models.DecimalField(max_digits=14, decimal_places=6, null=True, blank=True)
    reserved_cost = models.DecimalField(max_digits=14, decimal_places=6, default=0)
    error_code = models.CharField(max_length=48, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    call_started_at = models.DateTimeField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    output_revision_ids = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "ai_modelrun"
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(fields=("household", "request_key"), name="ai_modelrun_request_unique"),
            models.CheckConstraint(condition=models.Q(task_kind__in=("question", "knowledge", "assessment", "variant")),
                name="ai_modelrun_task_valid"),
            models.CheckConstraint(condition=models.Q(status__in=("queued", "running", "awaiting_review",
                "failed", "cancelled", "stale", "applied")), name="ai_modelrun_status_valid"),
            models.CheckConstraint(condition=models.Q(reserved_cost__gte=0), name="ai_modelrun_reserved_nonnegative"),
            models.CheckConstraint(condition=models.Q(estimated_cost__isnull=True) | models.Q(estimated_cost__gte=0),
                name="ai_modelrun_estimated_nonnegative"),
        ]
        indexes = [models.Index(fields=("household", "status", "created_at"), name="ai_modelrun_queue")]


class ModelBudgetReservation(models.Model):
    class State(models.TextChoices):
        HELD = "held", "已预留"
        SETTLED = "settled", "已结算"
        UNKNOWN = "unknown", "结果未知"
        RELEASED = "released", "已释放"

    run = models.OneToOneField(ModelRun, on_delete=models.PROTECT, related_name="budget_reservation")
    config = models.ForeignKey(ModelConfig, on_delete=models.PROTECT, related_name="budget_reservations")
    reserved_calls = models.PositiveSmallIntegerField(default=1)
    reserved_cost = models.DecimalField(max_digits=14, decimal_places=6)
    actual_calls = models.PositiveSmallIntegerField(default=0)
    actual_cost = models.DecimalField(max_digits=14, decimal_places=6, default=0)
    state = models.CharField(max_length=12, choices=State.choices, default=State.HELD)
    created_at = models.DateTimeField(auto_now_add=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ai_budgetreservation"
        constraints = [
            models.CheckConstraint(condition=models.Q(reserved_calls__gte=1), name="ai_budget_calls_positive"),
            models.CheckConstraint(condition=models.Q(reserved_cost__gte=0), name="ai_budget_reserved_nonnegative"),
            models.CheckConstraint(condition=models.Q(actual_cost__gte=0), name="ai_budget_actual_nonnegative"),
            models.CheckConstraint(condition=models.Q(state__in=("held", "settled", "unknown", "released")),
                name="ai_budget_state_valid"),
        ]
