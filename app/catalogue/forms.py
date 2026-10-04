"""Bounded, server-validated forms for splitting and merging questions."""
import json

from django import forms
from app.web.presentation import household_choices
from django.core.exceptions import ValidationError

from app.web.forms import RequestForm


class HouseholdForm(forms.Form):
    household_id = forms.ChoiceField(label="家庭", choices=())

    def __init__(self, *args, households=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["household_id"].choices = household_choices(households)


class SplitForm(RequestForm):
    household_id = forms.CharField(widget=forms.HiddenInput)
    source_revision_id = forms.CharField(max_length=160, widget=forms.HiddenInput)
    context_token = forms.CharField(widget=forms.HiddenInput)
    reason = forms.CharField(max_length=1000, label="拆题说明", widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for index in range(1, 6):
            required = index < 3
            self.fields[f"child_{index}_number"] = forms.CharField(max_length=80, required=required,
                label=f"子题 {index} 原资料题号")
            self.fields[f"child_{index}_text"] = forms.CharField(max_length=20000, required=False,
                label=f"子题 {index} 印刷题干", widget=forms.Textarea(attrs={"rows": 5}))

    def clean(self):
        cleaned = super().clean()
        children = []
        numbers = set()
        gap_seen = False
        for index in range(1, 6):
            number = (cleaned.get(f"child_{index}_number") or "").strip()
            text = (cleaned.get(f"child_{index}_text") or "").strip()
            if not number and not text:
                gap_seen = True
                continue
            if gap_seen:
                self.add_error(f"child_{index}_number", "请按顺序填写子题，不要跳过中间编号。")
            if not number:
                self.add_error(f"child_{index}_number", "请填写此子题的原资料题号。")
            elif number in numbers:
                self.add_error(f"child_{index}_number", "子题题号不能重复。")
            else:
                numbers.add(number)
                children.append({"original_number": number, "printed_text": text})
        if len(children) < 2:
            raise ValidationError("拆题至少要建立两个子题。")
        cleaned["children"] = children
        return cleaned


class MergeSelectionForm(forms.Form):
    household_id = forms.CharField(widget=forms.HiddenInput)
    source_revision_ids = forms.MultipleChoiceField(label="合并来源题目（当前版本）", choices=(),
        widget=forms.CheckboxSelectMultiple)

    def __init__(self, *args, question_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["source_revision_ids"].choices = list(question_choices)

    def clean_source_revision_ids(self):
        values = self.cleaned_data["source_revision_ids"]
        if len(values) < 2:
            raise ValidationError("合题至少选择两个不同的当前题目版本。")
        if len(values) > 20:
            raise ValidationError("一次最多合并 20 个题目版本。")
        if len(values) != len(set(values)):
            raise ValidationError("来源题目不能重复选择。")
        return values


class MergeForm(RequestForm):
    household_id = forms.CharField(widget=forms.HiddenInput)
    context_token = forms.CharField(widget=forms.HiddenInput)
    source_revision_ids = forms.CharField(widget=forms.HiddenInput)
    original_number = forms.CharField(max_length=80, label="合并后原资料题号")
    printed_text = forms.CharField(max_length=20000, required=False, label="合并后印刷题干",
        widget=forms.Textarea(attrs={"rows": 8}),
        help_text="人工写入合并后的题干；留空会作为题干待补的草稿保存。")
    reason = forms.CharField(max_length=1000, label="合题说明", widget=forms.Textarea(attrs={"rows": 3}))

    def clean_source_revision_ids(self):
        try:
            values = json.loads(self.cleaned_data["source_revision_ids"])
        except (TypeError, ValueError) as exc:
            raise ValidationError("合并来源无效，请重新选择。") from exc
        if (not isinstance(values, list) or not 2 <= len(values) <= 20
                or any(not isinstance(value, str) or not value for value in values)
                or len(values) != len(set(values))):
            raise ValidationError("合并来源必须是 2 至 20 个不重复的当前题目版本。")
        return values
