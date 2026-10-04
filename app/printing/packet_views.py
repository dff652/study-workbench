from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from app.exports.contracts import ExportError
from app.persistence import services as core
from app.web.views import _failure
from . import packets


@login_required
@never_cache
@require_http_methods(['GET','POST'])
def prepare(request,material_id):
    try:
        state=packets.readiness(request.user,material_id)
        if request.method=='POST':
            learner=request.POST.get('learner_id') or None
            if learner is not None:
                try:learner=int(learner)
                except ValueError:raise core.PersistenceError('invalid_input','请选择当前家庭的学习者。')
            packet_id=packets.generate(request.user,material_id,learner_id=learner)
            return redirect('printing:packet',material_id=material_id,packet_id=packet_id)
    except ObjectDoesNotExist:raise Http404
    except (core.PersistenceError,ExportError) as exc:return _failure(request,exc)
    return render(request,'printing/packet_prepare.html',state)


@login_required
@never_cache
@require_GET
def detail(request,material_id,packet_id):
    try:material,manifest=packets.read(request.user,material_id,packet_id)
    except ObjectDoesNotExist:raise Http404
    except (core.PersistenceError,ExportError) as exc:return _failure(request,exc)
    return render(request,'printing/packet.html',{'material':material,'manifest':manifest,'packet_id':packet_id})


@login_required
@never_cache
@require_GET
def download(request,material_id,packet_id):
    try:spool=packets.archive(request.user,material_id,packet_id)
    except ObjectDoesNotExist:raise Http404
    except (core.PersistenceError,ExportError) as exc:return _failure(request,exc)
    return FileResponse(spool,as_attachment=True,filename='study-workbench-five-books-'+packet_id[:12]+'.zip')
