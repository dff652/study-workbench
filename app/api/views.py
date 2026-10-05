"""Same-origin JSON adapters; authorization remains in the business services."""
from functools import wraps
import mimetypes
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, SuspiciousOperation
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.http.response import HttpResponseBase
from django.middleware.csrf import get_token
from django.urls import reverse
from django.views.decorators.cache import never_cache

from app.persistence import services as core
from app.persistence.models import EntityRecord
from app.release import identity
from app.exports.contracts import ExportError
from app.web import learning_services as learning
from . import evidence


def response(data, status=200):
    return JsonResponse({"schema_version": "swb.api.v1", **data}, status=status,
                        json_dumps_params={"ensure_ascii": False})


def error(code, message, status):
    return response({"error": {"code": code, "message": message}}, status)


MESSAGES = {
    "preparation_incomplete": "还有内容阶段待核对或明确取消，请先完成资料准备。",
    "model_disabled": "模型尚未启用，请先使用人工核对，或在设置中配置模型。",
    "model_scope": "模型配置尚未允许选定图像区域，请由家庭所有者核对外发范围。",
    "batch_expired": "本批次准备时间已到，请保留历史并建立新任务。",
    "batch_call_limit": "本批次已达到累计请求上限，重做不会重置已用次数。",
    "invalid_exchange": "交换包的内容、来源或区域不完整。请按工具交换说明核对输入。",
    "packet_incomplete": "还有题干、来源或家长答案待核对，请完成待补清单。",
    "source_changed": "资料或关联版本已更新，请保留历史并建立新任务。",
    "request_conflict": "本次请求已对应其他内容，请刷新后重新操作。",
    "output_unchecked": "请检查 PDF、Word 和五册用途后再完成交付。",
    "invalid_state": "任务阶段已变化，请刷新后选择当前可用的操作。",
    "upload_too_large": "单张照片不能超过 12 MiB。",
    "invalid_image": "请选择可完整读取的 JPEG 或 PNG 照片。",
}


def api(method="GET"):
    def decorate(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated or not request.user.is_active:
                return error("unauthorized", "请先登录。", 401)
            if request.method != method:
                result = error("method_not_allowed", "请求方法不支持。", 405)
                result["Allow"] = method
                return result
            try:
                result = view(request, *args, **kwargs)
                return result if isinstance(result, HttpResponseBase) else response(result)
            except (ObjectDoesNotExist, Http404):
                return error("not_found", "没有找到可访问的记录。", 404)
            except (core.PersistenceError, ExportError) as exc:
                status = 404 if exc.code in {"not_found", "permission_denied", "unauthorized", "object_not_found"} else 409 if any(x in exc.code for x in ("stale", "conflict", "changed")) else 400
                if isinstance(exc, core.PersistenceError) and exc.code in {"invalid_solution", "solution_incomplete", "stale_solution", "invalid_knowledge", "knowledge_incomplete", "invalid_subject", "stale_subject"}:
                    return error(exc.code, str(exc), status)
                return error(exc.code, MESSAGES.get(exc.code, "记录已变化，请刷新。" if status == 409 else "无法完成请求，请核对输入或访问权限。"), status)
            except (ValueError, TypeError, SuspiciousOperation):
                return error("invalid_input", "输入无效，请核对后重试。", 400)
        return never_cache(wrapped)
    return decorate


def household(request):
    selected = request.GET.get("household")
    rows = learning.household_options(request.user)
    if selected is None:
        return str(rows[0].household_id) if rows else None
    if not any(str(row.household_id) == selected for row in rows):
        raise Http404
    return selected


@api()
def session(request):
    rows = list(learning.household_options(request.user))
    return {"user": {"username": request.user.get_username()}, "csrf_token": get_token(request),
        "households": [{"id": str(row.household_id), "name": "我的家庭" if len(rows) == 1 else f"家庭 {index}", "role": row.role}
                       for index, row in enumerate(rows, 1)]}


@api()
def about(request):
    return identity()


@api()
def learners(request):
    hid = household(request)
    if hid is None:
        return {"items": []}
    bundle = core.read_snapshot_bundle(request.user, hid)
    pks = dict(EntityRecord.objects.filter(household_id=hid, kind="learner").values_list("stable_id", "pk"))
    return {"items": [{"id": row.learner_id, "display_name": row.display_name, "grade": row.grade,
        "profile_url": reverse("learning:profile_detail", args=[row.learner_id]),
        "report_url": reverse("study:report", args=[pks[row.learner_id]])}
        for row in sorted(bundle.learners, key=lambda row: row.display_name.casefold())]}


@api()
def overview(request, learner_id):
    data = evidence.projection(request.user, household(request), learner_id, request.GET)
    data.pop("items")
    return data


@api()
def attempts(request, learner_id):
    data = evidence.projection(request.user, household(request), learner_id, request.GET)
    page, size = int(request.GET.get("page", "1")), int(request.GET.get("page_size", "20"))
    if page < 1 or not 1 <= size <= 100:
        raise ValueError
    rows = data.pop("items")
    return {"scope": data["scope"], "items": rows[(page-1)*size:page*size],
            "total": len(rows), "page": page, "page_size": size}


def frontend_root():
    return Path(getattr(settings, "SWB_FRONTEND_ROOT", Path(__file__).resolve().parents[2] / "frontend" / "dist")).resolve()


@never_cache
def frontend(request, route=""):
    if request.method != "GET":
        return HttpResponse(status=405)
    path = frontend_root() / "index.html"
    if not path.is_file():
        return HttpResponse("前端尚未构建；请使用原有工作台入口。", status=503, content_type="text/plain; charset=utf-8")
    return HttpResponse(path.read_text(encoding="utf-8"), content_type="text/html; charset=utf-8")


@never_cache
def frontend_asset(request, name):
    if request.method != "GET":
        return HttpResponse(status=405)
    root = (frontend_root() / "assets").resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise Http404
    return FileResponse(path.open("rb"), content_type=mimetypes.guess_type(path)[0] or "application/octet-stream")
