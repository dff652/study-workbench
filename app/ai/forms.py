from uuid import uuid4

from django import forms

from .models import ModelConfig


class ModelConfigForm(forms.Form):
    provider_label = forms.CharField(max_length=120, label="供应商或网关名称")
    base_url = forms.URLField(max_length=500, label="兼容 API 地址")
    model = forms.CharField(max_length=160, label="模型名称")
    connection_route = forms.ChoiceField(choices=(('', "请选择"), *ModelConfig.ConnectionRoute.choices),
        label="连接路径")
    upstream_state = forms.ChoiceField(choices=(('', "请选择"), *ModelConfig.DeclarationState.choices),
        label="上游信息状态")
    known_upstream_providers = forms.CharField(required=False, max_length=2000,
        label="已知上游供应商（每行一项）", widget=forms.Textarea(attrs={"rows": 3}),
        help_text="若上游不明，请在上项明确选择“未知”，不要猜测。")
    retention_state = forms.ChoiceField(choices=(('', "请选择"), *ModelConfig.DeclarationState.choices),
        label="供应商留存说明状态")
    retention_description = forms.CharField(required=False, max_length=2000,
        label="供应商留存说明", widget=forms.Textarea(attrs={"rows": 3}),
        help_text="可说明留存期限、训练使用和删除能力；不明时明确选择“未知”。")
    cloud_enabled = forms.BooleanField(required=False, label="启用远程模型调用")
    confirm_external_processing = forms.BooleanField(required=False,
        label="我已核对以上供应商、上游、留存和外发范围，并确认启用外发",
        help_text="每次追加配置都要重新手动勾选。空白或迁移前配置不构成确认。")
    outbound_scope = forms.ChoiceField(choices=(
        (ModelConfig.OutboundScope.REVIEWED_TEXT, "仅外发已选的已发布文字"),
        (ModelConfig.OutboundScope.SELECTED_REGIONS, "已选文字及主动选择的图像区域"),
    ), label="外发范围")
    timeout_seconds = forms.IntegerField(min_value=1, max_value=60, initial=30, label="超时秒数")
    max_output_tokens = forms.IntegerField(min_value=1, max_value=2000, initial=1000, label="最大输出 token")
    max_input_chars = forms.IntegerField(min_value=1, max_value=16000, initial=16000, label="最大输入字符")
    max_calls = forms.IntegerField(min_value=1, max_value=4, initial=4, label="最多本地工具调用数")
    batch_budget = forms.DecimalField(max_digits=14, decimal_places=6, min_value=0, initial=0, label="本批预算上限（USD）")
    input_price_per_million = forms.DecimalField(max_digits=14, decimal_places=6, min_value=0,
        initial=0, label="输入价格（USD/百万 token）")
    output_price_per_million = forms.DecimalField(max_digits=14, decimal_places=6, min_value=0,
        initial=0, label="输出价格（USD/百万 token）")
    reserved_per_call = forms.DecimalField(max_digits=14, decimal_places=6, min_value=0,
        initial=0, label="含图片调用固定保守预留（USD）")
    non_billable_gateway = forms.BooleanField(required=False, label="明确使用非计价网关")

    def clean(self):
        cleaned = super().clean()
        for state_field, detail_field, label in (
                ("upstream_state", "known_upstream_providers", "上游名单"),
                ("retention_state", "retention_description", "留存说明")):
            state, detail = cleaned.get(state_field), cleaned.get(detail_field, "").strip()
            if state == ModelConfig.DeclarationState.KNOWN and not detail:
                self.add_error(detail_field, f"已知时请填写{label}，或将状态明确设为未知。")
            elif state == ModelConfig.DeclarationState.UNKNOWN and detail:
                self.add_error(detail_field, f"状态为未知时请清空{label}。")
            else:
                cleaned[detail_field] = detail
        if cleaned.get("cloud_enabled") and not cleaned.get("confirm_external_processing"):
            self.add_error("confirm_external_processing", "启用外发前须由你手动勾选确认。")
        if cleaned.get("confirm_external_processing") and not cleaned.get("cloud_enabled"):
            self.add_error("confirm_external_processing", "请先启用远程模型调用，再确认外发。")
        return cleaned


class RunSelectionForm(forms.Form):
    task_kind = forms.CharField(widget=forms.HiddenInput)
    selection_token = forms.CharField(widget=forms.HiddenInput)
    request_key = forms.CharField(max_length=160, widget=forms.HiddenInput)
    source_revision_ids = forms.MultipleChoiceField(required=False, label="已核对来源版本",
        widget=forms.SelectMultiple(attrs={"size": "8"}))
    question_revision_ids = forms.MultipleChoiceField(required=False, label="固定题目版本",
        widget=forms.SelectMultiple(attrs={"size": "6"}))
    attempt_revision_id = forms.ChoiceField(required=False, label="固定作答版本")
    selected_region_revision_ids = forms.MultipleChoiceField(required=False,
        label="主动选择发送的图像区域", widget=forms.SelectMultiple(attrs={"size": "8"}))
    include_attempt_text = forms.BooleanField(required=False, label="明确同意发送此作答版本的手工录入答案文本")

    def __init__(self, *args, context, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["task_kind"].initial = context["task_kind"]
        self.fields["selection_token"].initial = context["token"]
        self.fields["request_key"].initial = uuid4().hex
        choices = [(str(row["revision_id"]), f"{row['kind']} · {row['label']}") for row in context["choices"]]
        questions = [(str(row["revision_id"]), row["label"]) for row in context["choices"] if row["kind"] == "question"]
        attempts = [("", "不选择作答")]
        attempts.extend((str(row["revision_id"]), f"作答版本 {row['revision_id']} · 题目版本 {row['question_revision_id']}")
            for row in context["attempts"])
        regions = [(str(row["revision_id"]), row["label"]) for row in context["region_choices"]]
        self.fields["source_revision_ids"].choices = choices
        self.fields["question_revision_ids"].choices = questions
        self.fields["attempt_revision_id"].choices = attempts
        self.fields["selected_region_revision_ids"].choices = regions
        if context["task_kind"] != "assessment":
            self.fields.pop("attempt_revision_id")
            self.fields.pop("include_attempt_text")
