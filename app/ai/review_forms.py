"""Explicit human confirmation fields for one completed model proposal."""
from django import forms


class ConfirmReviewForm(forms.Form):
    context = forms.CharField(widget=forms.HiddenInput, max_length=16000)
    request_key = forms.CharField(widget=forms.HiddenInput, max_length=64)
    checked = forms.BooleanField(label="已逐项核对，未知仍保留未知", required=True)
    reason = forms.CharField(label="核对依据", widget=forms.Textarea, max_length=1000)

    def clean(self):
        cleaned = super().clean()
        submitted = set(self.data.keys()) | set(self.files.keys())
        unexpected = submitted - set(self.fields) - {"csrfmiddlewaretoken"}
        if unexpected:
            raise forms.ValidationError("表单包含不支持的字段，请刷新后重试。")
        return cleaned
