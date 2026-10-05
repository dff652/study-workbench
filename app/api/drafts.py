"""Optimistic, user-private drafts. Saving is intentionally not confirmation."""
import json
import math
import re

from django.db import transaction
from app.persistence import services as core
from app.web import records
from app.workflows.models import WorkspaceDraft
from .views import api, household, response

KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_:/.-]{0,159}\Z")
SENSITIVE = {"password", "password1", "password2", "passwd", "api_key", "api_secret", "secret", "token",
             "access_token", "refresh_token", "private_key", "authorization", "csrfmiddlewaretoken", "context_token", "request_key"}


def public(row):
    return {"key": row.key, "version": row.version, "base_stamp": row.base_stamp,
            "payload": row.payload, "updated_at": row.updated_at.isoformat()}


def validate(payload, depth=0):
    if depth > 12:
        raise ValueError("Draft nesting is too deep")
    if isinstance(payload, dict):
        if str(payload.get('name', '')).lower() in SENSITIVE:
            raise ValueError("Sensitive draft control")
        for key, value in payload.items():
            if not isinstance(key, str) or key.lower() in SENSITIVE or len(key) > 200 or "\x00" in key:
                raise ValueError("Sensitive or invalid draft field")
            validate(value, depth + 1)
    elif isinstance(payload, list):
        if len(payload) > 1000:
            raise ValueError("Too many draft fields")
        for value in payload:
            validate(value, depth + 1)
    elif type(payload) is str and "\x00" in payload:
        raise ValueError("Invalid draft text")
    elif type(payload) is float and not math.isfinite(payload):
        raise ValueError("Invalid draft number")
    elif payload is not None and type(payload) not in (str, bool, int, float):
        raise ValueError("Invalid draft value")


def scope(request, key, write=False):
    if not KEY.fullmatch(key):
        raise ValueError("Invalid draft identity")
    return records.household(request.user, household(request), write=write)


@api()
@transaction.atomic
def detail(request, key):
    owner = scope(request, key)
    row = WorkspaceDraft.objects.filter(household=owner, actor=request.user, key=key).first()
    return {"draft": public(row) if row else None}


@api("POST")
@transaction.atomic
def save(request, key):
    owner = scope(request, key, write=True)
    # Serialize first creation as well as updates, including separate browser tabs.
    type(owner).objects.select_for_update().get(pk=owner.pk)
    if len(request.body) > 1_100_000:
        raise ValueError("Draft too large")
    def unique_pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate draft field")
            result[key] = value
        return result
    try:
        data = json.loads(request.body, object_pairs_hook=unique_pairs)
    except (RecursionError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid draft JSON") from exc
    if type(data) is not dict or set(data) != {"expected_version", "base_stamp", "payload", "request_key"}:
        raise ValueError("Invalid draft contract")
    if type(data["expected_version"]) is not int or data["expected_version"] < 0:
        raise ValueError("Invalid expected version")
    if not isinstance(data["base_stamp"], str) or len(data["base_stamp"]) > 128 or "\x00" in data["base_stamp"]:
        raise ValueError("Invalid base stamp")
    if not isinstance(data["request_key"], str) or "\x00" in data["request_key"]:
        raise ValueError("Invalid request key")
    validate(data["payload"])
    fingerprint = core._digest({"key": key, **data})
    replay = core._replay(owner, request.user, data["request_key"], "web_record", fingerprint)
    if replay:
        return replay
    row = WorkspaceDraft.objects.filter(household=owner, actor=request.user, key=key).first()
    if (row.version if row else 0) != data["expected_version"]:
        return response({"error": {"code": "draft_conflict", "message": "另一窗口已保存较新的草稿。本次输入仍保留，请比较后再保存。"},
                         "draft": public(row) if row else None}, status=409)
    if row is None:
        row = WorkspaceDraft(household=owner, actor=request.user, key=key, version=1)
    else:
        row.version += 1
    row.payload = data["payload"]
    row.base_stamp = data["base_stamp"]
    row.save()
    return core._receipt(owner, request.user, data["request_key"], "web_record", fingerprint, {"draft": public(row)})
