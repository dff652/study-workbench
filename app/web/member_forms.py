"""Forms for creating and managing household login memberships."""
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from app.persistence.models import HouseholdMember
from . import member_services


MEMBER_ROLE_CHOICES = (
    (HouseholdMember.Role.REVIEWER, "审核成员"),
    (HouseholdMember.Role.VIEWER, "只读成员"),
)


class HouseholdForm(forms.Form):
    household_id = forms.CharField(max_length=160, widget=forms.HiddenInput)

    def clean(self):
        cleaned = super().clean()
        unexpected = set(self.data.keys()) - set(self.fields) - {"csrfmiddlewaretoken"}
        if unexpected:
            raise forms.ValidationError("提交包含不支持的字段。")
        return cleaned


class MemberCreateForm(HouseholdForm):
    action = forms.ChoiceField(choices=(("create", "create"),), widget=forms.HiddenInput)
    username = forms.CharField(
        max_length=1024,
        label="登录名",
        widget=forms.TextInput(attrs={"autocomplete": "username"}),
    )
    password1 = forms.CharField(
        max_length=1024,
        strip=False,
        label="密码",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}, render_value=False),
    )
    password2 = forms.CharField(
        max_length=1024,
        strip=False,
        label="再次输入密码",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}, render_value=False),
    )
    role = forms.ChoiceField(choices=MEMBER_ROLE_CHOICES, label="家庭角色")

    def clean_username(self):
        username = self.cleaned_data["username"]
        try:
            normalized = member_services.normalize_username(username)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages) from exc
        user_model = get_user_model()
        if user_model._default_manager.filter(**{user_model.USERNAME_FIELD: normalized}).exists():
            raise forms.ValidationError("此登录名已经存在；请使用其他登录名。")
        return normalized

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password1")
        confirmation = cleaned.get("password2")
        if password is not None and confirmation is not None and password != confirmation:
            self.add_error("password2", "两次输入的密码不一致。")
        username = cleaned.get("username")
        if username is not None and password is not None and confirmation == password:
            user_model = get_user_model()
            candidate = user_model()
            setattr(candidate, user_model.USERNAME_FIELD, username)
            try:
                validate_password(password, user=candidate)
            except ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned


class MemberRoleForm(HouseholdForm):
    action = forms.ChoiceField(choices=(("change", "change"),), widget=forms.HiddenInput)
    member_id = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    role = forms.ChoiceField(choices=MEMBER_ROLE_CHOICES, label="家庭角色")


class MemberRemoveForm(HouseholdForm):
    action = forms.ChoiceField(choices=(("remove", "remove"),), widget=forms.HiddenInput)
    member_id = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
