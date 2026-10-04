"""Closed HTML forms for learner, observation, attempt and assessment writes."""
import json
import math
from uuid import UUID

from django import forms
from app.web.presentation import household_choices

from app.domain import (
    ActualDateState, AttemptKind, BasisKind, DimensionKind, Independence,
    Judgment, Legibility, PromptStatus, SourceKind,
)
from .learning_labels import (
    ATTEMPT_KIND_LABELS, BASIS_LABELS, DIMENSION_LABELS, INDEPENDENCE_LABELS,
    JUDGMENT_LABELS, LEGIBILITY_LABELS, PROMPT_STATUS_LABELS, SOURCE_KIND_LABELS,
)


class RequestForm(forms.Form):
    request_key = forms.UUIDField(widget=forms.HiddenInput)


class ProfileForm(RequestForm):
    household_id = forms.ChoiceField(label="家庭", choices=())
    display_name = forms.CharField(max_length=120, label="学习者称呼")
    grade = forms.CharField(max_length=80, required=False, label="年级（可选）")

    def __init__(self, *args, households=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["household_id"].choices = household_choices(households)


class SourceFieldsMixin:
    def clean_sources(self):
        raw = self.cleaned_data.get("sources", "[]")
        try:
            values = json.loads(raw)
            if not isinstance(values, list) or len(values) > 30:
                raise ValueError
            for source in values:
                if not isinstance(source, dict):
                    raise ValueError
                UUID(source["page_id"])
                if type(source["rotation"]) is not int or source["rotation"] not in (0, 90, 180, 270):
                    raise ValueError
                if not isinstance(source["preview_sha256"], str) or len(source["preview_sha256"]) != 64:
                    raise ValueError
                bbox = source["display_bbox"]
                if (not isinstance(bbox, list) or len(bbox) != 4
                        or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in bbox)):
                    raise ValueError
            return values
        except (TypeError, ValueError, KeyError, AttributeError):
            raise forms.ValidationError("原图区域无效，请重新框选。")


class ObservationForm(RequestForm, SourceFieldsMixin):
    household_id = forms.CharField(widget=forms.HiddenInput)
    profile_context_id = forms.ChoiceField(required=False, label="档案上下文", choices=(),
        help_text="仅表示记录放在哪个档案下，不代表确认笔迹作者。")
    legibility = forms.ChoiceField(label="可读性", choices=list(LEGIBILITY_LABELS.items()))
    author_state = forms.ChoiceField(label="笔迹作者", choices=[("unknown", "来源不明／尚未确认"), ("confirmed", "人工确认作者")])
    author_learner_id = forms.ChoiceField(required=False, label="确认的学习者", choices=())
    confirmation_basis = forms.CharField(required=False, max_length=1000,
        widget=forms.Textarea(attrs={"rows": 2}), label="作者确认依据")
    actual_date_state = forms.ChoiceField(label="实际发生日期", choices=[("unknown", "日期未知"), ("known", "已确认日期")])
    actual_date = forms.DateField(required=False, input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}), label="实际发生日期")
    notes = forms.CharField(max_length=2000, widget=forms.Textarea(attrs={"rows": 3}),
        label="观察说明／证据缺口")
    sources = forms.CharField(required=False, widget=forms.HiddenInput, initial="[]", label="原图区域")
    clear_sources = forms.BooleanField(required=False, label="清除此修订的来源区域（旧版本仍保留）")
    reason = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={"rows": 2}), label="修订说明")
    context_token = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, profiles=(), **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", "不关联档案")]
        choices.extend((item.learner_id, item.display_name) for item in profiles)
        self.fields["profile_context_id"].choices = choices
        self.fields["author_learner_id"].choices = [("", "请选择")]+[(item.learner_id, item.display_name) for item in profiles]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("author_state") == "confirmed":
            if not cleaned.get("author_learner_id") or not cleaned.get("confirmation_basis", "").strip():
                self.add_error("confirmation_basis", "确认作者时需选择学习者并写明依据。")
        if cleaned.get("actual_date_state") == "known" and not cleaned.get("actual_date"):
            self.add_error("actual_date", "请填写实际发生日期。")
        if cleaned.get("actual_date_state") == "unknown" and cleaned.get("actual_date"):
            self.add_error("actual_date", "日期未知时请清空日期；不能用录入或上传日期代替。")
        if not cleaned.get("notes", "").strip():
            self.add_error("notes", "请记录观察说明；没有来源区域时尤其要写明证据缺口。")
        return cleaned


class AttemptForm(RequestForm):
    learner_id = forms.CharField(widget=forms.HiddenInput, required=False)
    question_id = forms.ChoiceField(label="题目", choices=())
    attempt_kind = forms.ChoiceField(label="本次类型", choices=list(ATTEMPT_KIND_LABELS.items()))
    source_kind = forms.ChoiceField(label="来源类型", choices=list(SOURCE_KIND_LABELS.items()))
    independence = forms.ChoiceField(label="独立性", choices=list(INDEPENDENCE_LABELS.items()))
    prompt_status = forms.ChoiceField(label="提示情况", choices=list(PROMPT_STATUS_LABELS.items()))
    prompts = forms.CharField(required=False, max_length=1200, widget=forms.Textarea(attrs={"rows": 2}),
        label="提示内容（每行一项）")
    actual_date_state = forms.ChoiceField(label="实际作答日期", choices=[("unknown", "日期未知"), ("known", "已确认日期")])
    actual_date = forms.DateField(required=False, input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}), label="实际作答日期")
    legibility = forms.ChoiceField(label="笔迹可读性", choices=[
        (value, LEGIBILITY_LABELS[value]) for value in (
            Legibility.READABLE.value, Legibility.PARTIAL.value, Legibility.ILLEGIBLE.value,
            Legibility.BLANK.value, Legibility.UNKNOWN.value)])
    answer_text = forms.CharField(required=False, max_length=10000, widget=forms.Textarea(attrs={"rows": 3}), label="答案转写")
    authorship_basis = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={"rows": 2}), label="作者确认依据")
    observation_values = forms.MultipleChoiceField(label="作者已确认的来源观察", choices=(), widget=forms.CheckboxSelectMultiple)
    previous_attempt_id = forms.ChoiceField(required=False, label="前次作答", choices=())
    reason = forms.CharField(required=False, max_length=1000, widget=forms.Textarea(attrs={"rows": 2}), label="修订说明")
    context_token = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, learner_id=None, learners=(), questions=(), observations=(), prior_attempts=(),
                 allow_identity=False, identity_locked=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["question_id"].choices = [(item["question_id"], item["label"]) for item in questions]
        self.fields["observation_values"].choices = list(observations)
        self.fields["previous_attempt_id"].choices = [("", "无")]+list(prior_attempts)
        if allow_identity:
            self.fields["learner_id"] = forms.ChoiceField(label="确认的学习者", choices=[(item.learner_id, item.display_name) for item in learners])
        elif learner_id:
            self.initial.setdefault("learner_id", learner_id)
        if identity_locked:
            self.fields["question_id"].disabled = True
            self.fields["previous_attempt_id"].disabled = True

    def clean_prompts(self):
        return [line.strip() for line in self.cleaned_data.get("prompts", "").splitlines() if line.strip()]

    def clean(self):
        cleaned = super().clean()
        source, independent = cleaned.get("source_kind"), cleaned.get("independence")
        prompt = cleaned.get("prompt_status")
        if source in (SourceKind.CLASSROOM_NOTE.value, SourceKind.COPIED_WORK.value) and independent == Independence.CONFIRMED_INDEPENDENT.value:
            self.add_error("independence", "课堂笔记或抄录不能确认独立。")
        if source == SourceKind.INDEPENDENT_ANSWER.value and independent == Independence.NOT_INDEPENDENT.value:
            self.add_error("independence", "来源为独立作答时不能标记为非独立。")
        if independent == Independence.CONFIRMED_INDEPENDENT.value and (
                source != SourceKind.INDEPENDENT_ANSWER.value or prompt != PromptStatus.NONE_CONFIRMED.value):
            self.add_error("prompt_status", "确认独立需要同时选择独立作答来源和人工确认无提示。")
        if cleaned.get("actual_date_state") == "known" and not cleaned.get("actual_date"):
            self.add_error("actual_date", "请填写实际作答日期。")
        if cleaned.get("actual_date_state") == "unknown" and cleaned.get("actual_date"):
            self.add_error("actual_date", "日期未知时请清空日期；不能用录入或上传日期代替。")
        if not cleaned.get("observation_values"):
            self.add_error("observation_values", "至少关联一条作者已确认且有原图证据的观察。")
        if cleaned.get("attempt_kind") != AttemptKind.FIRST.value and not cleaned.get("previous_attempt_id"):
            self.add_error("previous_attempt_id", "订正、重做和复测需要选择前次作答。")
        if cleaned.get("attempt_kind") == AttemptKind.FIRST.value and cleaned.get("previous_attempt_id"):
            self.add_error("previous_attempt_id", "首次作答不能引用前次作答。")
        if cleaned.get("legibility") in (Legibility.BLANK.value, Legibility.ILLEGIBLE.value) and cleaned.get("answer_text", "").strip():
            self.add_error("answer_text", "空白或看不清的笔迹不能转写为答案。")
        return cleaned


class CorrectionForm(AttemptForm):
    def __init__(self, *args, **kwargs):
        kwargs["allow_identity"] = True
        super().__init__(*args, **kwargs)


class AssessmentForm(RequestForm):
    reason = forms.CharField(required=False, max_length=1000,
        widget=forms.Textarea(attrs={"rows": 2}), label="本次评价说明")
    context_errata = forms.MultipleChoiceField(required=False, label="已审核的讲义勘误（可选）", choices=(),
        widget=forms.CheckboxSelectMultiple)
    context_token = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, evidence_choices=(), errata_choices=(), initial_dimensions=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["context_errata"].choices = list(errata_choices)
        self.dimension_fields = []
        initial_dimensions = initial_dimensions or {}
        for kind in (DimensionKind.ANSWER, DimensionKind.METHOD, DimensionKind.PROCESS,
                     DimensionKind.CALCULATION, DimensionKind.NOTATION):
            key = kind.value
            choices = {
                "judgment": list(JUDGMENT_LABELS.items()),
                "basis": list(BASIS_LABELS.items()),
            }
            values = initial_dimensions.get(key, {})
            defaults = {"judgment": Judgment.UNKNOWN.value, "basis": BasisKind.UNDETERMINED.value,
                        "unknown_reason": "当前证据不足，保留未知。", "rationale": ""}
            defaults.update(values)
            self.fields[f"{key}_judgment"] = forms.ChoiceField(label=f"{DIMENSION_LABELS[key]}判断", choices=choices["judgment"], initial=defaults["judgment"])
            self.fields[f"{key}_basis"] = forms.ChoiceField(label=f"{DIMENSION_LABELS[key]}依据", choices=choices["basis"], initial=defaults["basis"])
            self.fields[f"{key}_evidence"] = forms.MultipleChoiceField(required=False, label=f"{DIMENSION_LABELS[key]}原图证据",
                choices=list(evidence_choices), widget=forms.CheckboxSelectMultiple, initial=defaults.get("evidence", []))
            self.fields[f"{key}_rationale"] = forms.CharField(required=False, max_length=2000,
                widget=forms.Textarea(attrs={"rows": 2}), label=f"{DIMENSION_LABELS[key]}判断依据", initial=defaults["rationale"])
            self.fields[f"{key}_unknown_reason"] = forms.CharField(required=False, max_length=1000,
                widget=forms.Textarea(attrs={"rows": 2}), label=f"{DIMENSION_LABELS[key]}未知原因", initial=defaults["unknown_reason"])
            self.dimension_fields.append({"key": key, "label": DIMENSION_LABELS[key], **{
                name: self[f"{key}_{name}"]
                for name in ("judgment", "basis", "evidence", "rationale", "unknown_reason")}})

    def clean(self):
        cleaned = super().clean()
        for dimension in self.dimension_fields:
            key = dimension["key"]
            judgment = cleaned.get(f"{key}_judgment")
            basis = cleaned.get(f"{key}_basis")
            evidence = cleaned.get(f"{key}_evidence") or []
            rationale = cleaned.get(f"{key}_rationale", "").strip()
            unknown_reason = cleaned.get(f"{key}_unknown_reason", "").strip()
            if judgment == Judgment.UNKNOWN.value and not unknown_reason:
                self.add_error(f"{key}_unknown_reason", "无法判断时必须说明未知原因。")
            if basis == BasisKind.UNDETERMINED.value and not unknown_reason:
                self.add_error(f"{key}_unknown_reason", "依据未确定时必须说明原因。")
            if basis == BasisKind.INFERRED.value and not rationale:
                self.add_error(f"{key}_rationale", "推测判断需要写明依据。")
            if judgment == Judgment.CORRECT.value and (basis != BasisKind.OBSERVED.value or not evidence):
                self.add_error(f"{key}_evidence", "正确判断必须直接观察并关联原图区域。")
            if basis == BasisKind.OBSERVED.value and judgment != Judgment.UNKNOWN.value and not evidence:
                self.add_error(f"{key}_evidence", "已观察判断需要关联原图区域。")
        return cleaned

    def dimension_values(self):
        return {kind.value: {"judgment": self.cleaned_data[f"{kind.value}_judgment"],
            "basis": self.cleaned_data[f"{kind.value}_basis"],
            "evidence": self.cleaned_data.get(f"{kind.value}_evidence", []),
            "rationale": self.cleaned_data.get(f"{kind.value}_rationale", ""),
            "unknown_reason": self.cleaned_data.get(f"{kind.value}_unknown_reason", "")}
            for kind in (DimensionKind.ANSWER, DimensionKind.METHOD, DimensionKind.PROCESS,
                         DimensionKind.CALCULATION, DimensionKind.NOTATION)}


class ReviewForm(RequestForm):
    revision_id = forms.CharField(max_length=160, widget=forms.HiddenInput)
    action = forms.ChoiceField(label="人工审核", choices=[("", "请选择"), ("accept", "接受"),
        ("reject", "退回"), ("withdraw", "撤回已接受评价")])
    reason = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={"rows": 2}), label="审核依据")
    context_token = forms.CharField(widget=forms.HiddenInput)
