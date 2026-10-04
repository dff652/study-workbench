"""Small, server-validated forms for the private manual workflow."""
import json
from uuid import UUID

from django import forms
from app.web.presentation import household_choices


class RequestForm(forms.Form):
    request_key = forms.UUIDField(widget=forms.HiddenInput)


class MaterialForm(RequestForm):
    household_id = forms.ChoiceField(label="家庭", choices=())
    title = forms.CharField(max_length=160, label="资料集名称")

    def __init__(self, *args, households=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["household_id"].choices = household_choices(households)
        if len(self.fields['household_id'].choices)==1:
            self.fields['household_id'].widget=forms.HiddenInput()
            self.initial['household_id']=self.fields['household_id'].choices[0][0]


class UploadPageForm(RequestForm):
    image = forms.FileField(label="照片", widget=forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png"}))


class ReorderPagesForm(RequestForm):
    ids = forms.CharField(widget=forms.HiddenInput, label="页面顺序")

    def clean_ids(self):
        raw = self.cleaned_data["ids"]
        try:
            values = json.loads(raw)
            if not isinstance(values, list) or not values:
                raise ValueError
            return [str(UUID(value)) for value in values]
        except (TypeError, ValueError, AttributeError):
            raise forms.ValidationError("页面顺序无效，请刷新后重试。")


class QuestionForm(RequestForm):
    original_number = forms.CharField(max_length=80, required=False, label="原资料题号")
    context_token = forms.CharField(required=False, widget=forms.HiddenInput)
    printed_text = forms.CharField(
        max_length=20000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 8, "autocomplete": "off"}),
        label="印刷题干",
        help_text="只录入印刷题干；手写答案、过程和作者留待后续作答记录处理。",
    )
    display_markup = forms.CharField(required=False, max_length=24000,
        label="排版文本（可选）", widget=forms.Textarea(attrs={"rows": 8}),
        help_text="整行公式 [[math:1/2]]；**重点**；==标记==；图片回退 [[image:1|原文]]，数字为来源区域序号。去标记后须与当前正文一致。")
    image_print_confirmed = forms.BooleanField(required=False,
        label="我已逐一核对本版打印图片，只包含题干或数学符号，没有作答、提示或方法笔记",
        help_text="有图片回退的独立练习必须人工核对。原图区域含手写答案时，请重新选择纯题干区域；每次修订重新核对。")
    sources = forms.CharField(widget=forms.HiddenInput, label="原图区域")
    reason = forms.CharField(
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="本次修订说明",
    )

    def clean_sources(self):
        raw = self.cleaned_data["sources"]
        try:
            sources = json.loads(raw)
            if not isinstance(sources, list) or not 1 <= len(sources) <= 30:
                raise ValueError
            for source in sources:
                if not isinstance(source, dict):
                    raise ValueError
                UUID(source["page_id"])
                if source["rotation"] not in (0, 90, 180, 270):
                    raise ValueError
                if not isinstance(source["preview_sha256"], str):
                    raise ValueError
                bbox = source["display_bbox"]
                if not isinstance(bbox, list) or len(bbox) != 4:
                    raise ValueError
            return sources
        except (TypeError, ValueError, KeyError, AttributeError):
            raise forms.ValidationError("原图区域无效，请重新框选。")


class ReviewForm(RequestForm):
    ACTIONS = (("", "请选择"), ("accept", "审核通过"), ("reject", "退回修改"), ("withdraw", "撤回审核"))

    revision_id = forms.CharField(max_length=160, widget=forms.HiddenInput)
    action = forms.ChoiceField(choices=ACTIONS, label="审核操作")
    reason = forms.CharField(
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="审核说明",
    )
    context_token = forms.CharField(widget=forms.HiddenInput)
