"""Closed forms for manual study schedule changes."""
from uuid import UUID

from django import forms


class RequestForm(forms.Form):
    request_key = forms.UUIDField(widget=forms.HiddenInput)
    context_token = forms.CharField(widget=forms.HiddenInput)


class ScheduleForm(RequestForm):
    question_revision_id = forms.ChoiceField(label="当前已发布题目版本", choices=())
    due_date = forms.DateField(label="复习日期", input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}))
    goal = forms.CharField(label="目标说明", max_length=1200,
        widget=forms.Textarea(attrs={"rows": 2}))
    prompt_plan = forms.CharField(label="提示安排（可留空）", required=False, max_length=2000,
        widget=forms.Textarea(attrs={"rows": 2}))
    reason = forms.CharField(label="计划依据", max_length=1000,
        widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, questions=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["question_revision_id"].choices = [
            (item["revision_id"], item["label"]) for item in questions]


class ScheduleEventForm(RequestForm):
    action = forms.ChoiceField(label="计划操作", choices=[
        ("rescheduled", "改期"), ("cancelled", "取消"), ("completed", "记录完成")])
    due_date = forms.DateField(label="新的计划日期", required=False, input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}))
    goal = forms.CharField(label="新的目标说明", required=False, max_length=1200,
        widget=forms.Textarea(attrs={"rows": 2}))
    prompt_plan = forms.CharField(label="提示安排", required=False, max_length=2000,
        widget=forms.Textarea(attrs={"rows": 2}))
    attempt_revision_id = forms.ChoiceField(label="绑定的实际作答版本", required=False, choices=())
    reason = forms.CharField(label="变更依据", max_length=1000,
        widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, attempts=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["attempt_revision_id"].choices = [("", "请选择一次作答")]+[
            (item["revision"].header.revision_id, item["label"]) for item in attempts]

    def clean(self):
        cleaned = super().clean()
        action = cleaned.get("action")
        if action == "rescheduled":
            if not cleaned.get("due_date"):
                self.add_error("due_date", "改期时请指定新的计划日期。")
            if not cleaned.get("goal", "").strip():
                self.add_error("goal", "改期时请填写目标说明。")
        elif action == "completed" and not cleaned.get("attempt_revision_id"):
            self.add_error("attempt_revision_id", "完成计划必须绑定一次实际作答。")
        return cleaned
