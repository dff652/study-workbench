"""Small, explicit form boundary for confirmed teaching diagrams."""
from django import forms


class DiagramForm(forms.Form):
    context = forms.CharField(widget=forms.HiddenInput, max_length=65536)
    request_key = forms.CharField(widget=forms.HiddenInput, max_length=64)
    placement = forms.ChoiceField(label="图示位置", choices=[("question", "题面图"), ("answer", "解析图")])
    source_region_id = forms.ChoiceField(label="对应原图区域", choices=[])
    png_upload = forms.FileField(label="PNG 题面图", widget=forms.ClearableFileInput(attrs={"accept": ".png,image/png"}))
    vector_upload = forms.FileField(label="配套 PDF／SVG 矢量来源",
        widget=forms.ClearableFileInput(attrs={"accept": ".pdf,.svg,application/pdf,image/svg+xml"}))
    alt = forms.CharField(label="图示说明", max_length=2000)
    conditions = forms.CharField(label="构造条件（每行一条）", widget=forms.Textarea,
        max_length=30000, help_text="1 至 30 条；显示出的条件和标注都须逐项核对。")
    width_points = forms.FloatField(label="打印宽度（点）", min_value=50, max_value=490)
    min_label_points = forms.FloatField(label="最小标注字号（点）", min_value=9, max_value=40)
    independent_safe = forms.BooleanField(label="确认题面图的标签和条件不含解题提示", required=False)
    content_checked = forms.BooleanField(label="已核对题干、标签和全部显示条件", required=True)
    basis = forms.CharField(label="核对依据", widget=forms.Textarea, max_length=4000)

    def clean_png_upload(self):
        upload = self.cleaned_data["png_upload"]
        if not upload.name.lower().endswith(".png"):
            raise forms.ValidationError("题面图文件名须以 .png 结尾。")
        return upload

    def clean_vector_upload(self):
        upload = self.cleaned_data["vector_upload"]
        if not upload.name.lower().endswith((".pdf", ".svg")):
            raise forms.ValidationError("矢量来源文件名须以 .pdf 或 .svg 结尾。")
        return upload

    def clean_conditions(self):
        values = [line.strip() for line in self.cleaned_data["conditions"].splitlines() if line.strip()]
        if not 1 <= len(values) <= 30 or any(len(value) > 1000 for value in values):
            raise forms.ValidationError("请填写 1 至 30 条非空条件，每条不超过 1000 字。")
        return values

    def clean(self):
        cleaned = super().clean()
        submitted = set(self.data.keys()) | set(self.files.keys())
        unexpected = submitted - set(self.fields) - {"csrfmiddlewaretoken"}
        if unexpected:
            raise forms.ValidationError("表单包含不支持的字段，请刷新后重试。")
        if cleaned.get("placement") != "question":
            cleaned["independent_safe"] = False
        return cleaned
