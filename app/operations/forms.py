"""Closed input forms for household retention and timing records."""
from django import forms

from .models import WorkTiming


class RequestForm(forms.Form):
    request_key = forms.UUIDField(widget=forms.HiddenInput)


class RetentionPolicyForm(RequestForm):
    archive_after_days = forms.IntegerField(label="导出归档期限（天）", required=False,
        min_value=0, max_value=36500,
        help_text="留空表示不自动归档；原始照片、领域历史和模型提案始终保留。")
    delete_after_days = forms.IntegerField(label="导出文件退役期限（天）", required=False,
        min_value=0, max_value=36500,
        help_text="留空表示不自动退役。启用时必须先归档；只退役导出快照目录。")
    reason = forms.CharField(label="本次策略依据", max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}))

    def clean(self):
        cleaned = super().clean()
        archive_days = cleaned.get("archive_after_days")
        delete_days = cleaned.get("delete_after_days")
        if delete_days is not None and archive_days is None:
            self.add_error("archive_after_days", "启用退役前须设置归档期限。")
        elif delete_days is not None and archive_days is not None and delete_days < archive_days:
            self.add_error("delete_after_days", "退役期限不能早于归档期限。")
        return cleaned


class WorkTimingForm(RequestForm):
    context_token = forms.CharField(widget=forms.HiddenInput)
    question_revision_id = forms.ChoiceField(label="当前已发布题目版本", choices=())
    attempt_revision_id = forms.ChoiceField(label="匹配的当前作答版本（可选）", required=False, choices=())
    kind = forms.ChoiceField(label="记录类型", choices=WorkTiming.Kind.choices)
    seconds = forms.IntegerField(label="估计用时（秒）", min_value=1, max_value=604800)
    reason = forms.CharField(label="估计依据", max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="这是明确标注的人工估计，不是后台精确计时。")

    def __init__(self, *args, questions=(), attempts=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["question_revision_id"].choices = questions
        self.fields["attempt_revision_id"].choices = [("", "只关联题目，不关联具体作答"), *attempts]
