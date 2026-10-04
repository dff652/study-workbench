"""Private owner-only views for household account membership."""
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from app.persistence.services import PersistenceError
from . import member_services
from .member_forms import MemberCreateForm, MemberRemoveForm, MemberRoleForm


LOGIN_URL = "/accounts/login/"


def _scope(request):
    household_id = request.GET.get("household_id") if request.method == "GET" else request.POST.get("household_id")
    if not household_id:
        raise Http404
    try:
        return member_services.list_members(request.user, household_id)
    except PersistenceError as exc:
        if exc.code in {"permission_denied", "not_found"}:
            raise Http404 from exc
        raise


def _render_members(
    request,
    data,
    *,
    household_choices=(),
    create_form=None,
    role_form=None,
    remove_form=None,
    error="",
    status=200,
):
    household_id = data["household"].pk
    member_rows = []
    for member in data["members"]:
        protected = (
            member.role == "owner"
            or getattr(member.user, "is_staff", False)
            or getattr(member.user, "is_superuser", False)
        )
        active_role_form = None
        active_remove_form = None
        if not protected:
            matches_role = role_form is not None and role_form.data.get("member_id") == str(member.pk)
            matches_remove = remove_form is not None and remove_form.data.get("member_id") == str(member.pk)
            active_role_form = role_form if matches_role else MemberRoleForm(
                initial={
                    "action": "change",
                    "household_id": household_id,
                    "member_id": member.pk,
                    "role": member.role,
                },
                auto_id=f"member-role-{member.pk}-%s",
            )
            active_remove_form = remove_form if matches_remove else MemberRemoveForm(initial={
                "action": "remove",
                "household_id": household_id,
                "member_id": member.pk,
            })
        member_rows.append({
            "membership": member,
            "protected": protected,
            "role_form": active_role_form,
            "remove_form": active_remove_form,
        })

    context = {
        "household": data["household"],
        "household_choices": household_choices,
        "selected_household_id": household_id,
        "member_rows": member_rows,
        "create_form": create_form or MemberCreateForm(
            initial={"action": "create", "household_id": household_id},
            auto_id="id_create_%s",
        ),
        "error": error,
    }
    return render(request, "web/members.html", context, status=status)


def _render_household_picker(request, households):
    return render(request, "web/members.html", {
        "household": None,
        "household_choices": households,
        "selected_household_id": "",
        "member_rows": [],
        "create_form": None,
        "error": "",
    })


def _redirect_to_members(household_id):
    query = urlencode({"household_id": household_id})
    return redirect(f"{reverse('web:members')}?{query}")


def _service_error(exc):
    if exc.code in {"permission_denied", "not_found"}:
        raise Http404 from exc
    messages = {
        "protected_member": "家庭所有者及系统管理账号不能在这里修改或移除。",
        "username_taken": "此登录名已经存在；请使用其他登录名。",
        "invalid_input": "提交内容无效，请检查后重试。",
        "account_creation_failed": "无法创建标准家庭成员账号。",
    }
    return messages.get(exc.code, "操作未完成，请检查输入后重试。")


@never_cache
@login_required(login_url=LOGIN_URL)
@require_http_methods(["GET", "POST"])
@csrf_protect
def index(request):
    if request.method == "GET":
        try:
            households = member_services.list_owner_households(request.user)
        except PersistenceError as exc:
            if exc.code in {"permission_denied", "not_found"}:
                raise Http404 from exc
            raise
        if not households:
            raise Http404
        household_id = request.GET.get("household_id")
        if not household_id:
            if len(households) > 1:
                return _render_household_picker(request, households)
            household_id = households[0].pk
        try:
            data = member_services.list_members(request.user, household_id)
        except PersistenceError as exc:
            if exc.code in {"permission_denied", "not_found"}:
                raise Http404 from exc
            raise
        return _render_members(request, data, household_choices=households)

    data = _scope(request)
    try:
        household_choices = member_services.list_owner_households(request.user)
    except PersistenceError as exc:
        if exc.code in {"permission_denied", "not_found"}:
            raise Http404 from exc
        raise

    action = request.POST.get("action", "")
    error = ""
    create_form = None
    role_form = None
    remove_form = None

    if action == "create":
        create_form = MemberCreateForm(request.POST, auto_id="id_create_%s")
        if create_form.is_valid():
            values = create_form.cleaned_data
            try:
                member_services.create_member(
                    request.user,
                    values["household_id"],
                    values["username"],
                    values["password1"],
                    values["role"],
                )
            except PersistenceError as exc:
                message = _service_error(exc)
                if exc.code == "username_taken":
                    create_form.add_error("username", message)
                else:
                    create_form.add_error(None, message)
            except ValidationError as exc:
                create_form.add_error("password1", exc)
            else:
                return _redirect_to_members(data["household"].pk)
        return _render_members(request, data, household_choices=household_choices, create_form=create_form, status=400)

    if action == "change":
        role_form = MemberRoleForm(request.POST)
        if role_form.is_valid():
            values = role_form.cleaned_data
            try:
                member_services.change_role(
                    request.user,
                    values["household_id"],
                    values["member_id"],
                    values["role"],
                )
            except PersistenceError as exc:
                error = _service_error(exc)
            else:
                return _redirect_to_members(data["household"].pk)
        else:
            error = "提交内容无效，请检查成员和角色。"
        return _render_members(request, data, household_choices=household_choices, role_form=role_form, error=error, status=400)

    if action == "remove":
        remove_form = MemberRemoveForm(request.POST)
        if remove_form.is_valid():
            values = remove_form.cleaned_data
            try:
                member_services.remove_member(request.user, values["household_id"], values["member_id"])
            except PersistenceError as exc:
                error = _service_error(exc)
            else:
                return _redirect_to_members(data["household"].pk)
        else:
            error = "提交内容无效，请检查成员。"
        return _render_members(request, data, household_choices=household_choices, remove_form=remove_form, error=error, status=400)

    return _render_members(request, data, household_choices=household_choices, error="未知操作。", status=400)
