"""Public installation metadata; the worker caches only a generic offline page."""
from hashlib import sha256
from pathlib import Path

from django.http import JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.http import require_safe


_ROOT = Path(__file__).resolve().parent
_OFFLINE = _ROOT / "static/web/pwa/offline.html"
_WORKER = _ROOT / "templates/web/service-worker.js"
_VERSION = sha256(_OFFLINE.read_bytes() + _WORKER.read_bytes()).hexdigest()[:16]


@require_safe
def manifest(request):
    return JsonResponse({
        "id": "/",
        "name": "学习资料工作台",
        "short_name": "学习工作台",
        "lang": "zh-Hans",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f2f5f8",
        "theme_color": "#153a50",
        "icons": [{"src": static(f"web/pwa/icon-{size}.png"),
                   "sizes": f"{size}x{size}", "type": "image/png", "purpose": "any"}
                  for size in (192, 512)],
    }, content_type="application/manifest+json")


@require_safe
def service_worker(request):
    response = render(request, "web/service-worker.js", {
        "offline_url": static("web/pwa/offline.html"),
        "cache_name": f"study-workbench-offline-{_VERSION}",
    }, content_type="application/javascript")
    response["Cache-Control"] = "no-store, no-cache, max-age=0"
    response["Service-Worker-Allowed"] = "/"
    return response


@require_safe
def mobile_help(request):
    return render(request, "web/mobile-help.html")
