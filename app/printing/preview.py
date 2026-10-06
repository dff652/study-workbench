"""Authorized on-demand page images, derived from the verified immutable PDF."""
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from app.persistence import services as core
from app.exports.contracts import ExportError
from . import services


@login_required
@never_cache
@require_GET
def page(request, pk, number):
    try:
        pdf = services.snapshot_file(request.user, pk, 'document.pdf')
        content = services.snapshot_file(request.user, pk, 'content.json')
        pages = json.loads(content.read_bytes()).get('pages', [])
        if not 1 <= number <= len(pages):
            raise Http404
    except (ObjectDoesNotExist, core.PersistenceError, ExportError):
        raise Http404
    executable = shutil.which('pdftoppm')
    if not executable:
        return HttpResponse('逐页预览暂不可用，请打开或下载 PDF。', status=503)
    with tempfile.TemporaryDirectory(prefix='swb-pdf-preview-') as temporary:
        destination = Path(temporary) / 'page'
        try:
            subprocess.run([executable, '-f', str(number), '-l', str(number), '-singlefile',
                '-scale-to', '1400', '-png', str(pdf), str(destination)], check=True,
                timeout=30, capture_output=True)
            image = destination.with_suffix('.png').read_bytes()
        except (subprocess.SubprocessError, OSError):
            return HttpResponse('逐页预览未完成，可重试或下载 PDF。', status=503)
    return FileResponse(BytesIO(image), content_type='image/png')


@login_required
@never_cache
@require_GET
def metadata(request, pk):
    try:
        content = services.snapshot_file(request.user, pk, 'content.json')
        pages = json.loads(content.read_bytes())['pages']
    except (ObjectDoesNotExist, core.PersistenceError, ExportError):
        raise Http404
    return JsonResponse({'pages': [reverse('printing:snapshot_preview', args=[pk, number])
        for number in range(1, len(pages) + 1)]})
