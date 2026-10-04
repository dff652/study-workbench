"""Private print and teacher-answer forms; all state changes require CSRF."""
import json
from uuid import uuid4
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods, require_GET
from app.persistence import services as core
from app.persistence.models import Household, EntityRecord, RevisionRecord
from app.exports.contracts import ExportError
from app.domain.arithmetic import ArithmeticError, formula_ast, check_arithmetic
from app.web import records
from app.web.views import _failure
from . import services
from .models import TeacherAnswerRevision, ExportSnapshot


class PrintForm(forms.Form):
    household = forms.ChoiceField(label='家庭')
    title = forms.CharField(label='标题',max_length=160,initial='独立练习')
    purpose = forms.ChoiceField(label='用途',choices=[('independent_practice','独立练习（无提示）'),
        ('parent_answers','家长答案（仅已审核答案）'),('knowledge_summary','知识整理'),('classification_index','分类索引')])
    questions = forms.MultipleChoiceField(label='当前已审核题目',widget=forms.CheckboxSelectMultiple)


class AnswerForm(forms.Form):
    body = forms.CharField(label='答案／解析',widget=forms.Textarea,max_length=20000)
    formulas = forms.CharField(label='可编辑公式（每行一条，可留空）',widget=forms.Textarea,required=False,
        help_text='例如 1/3 + 1/6 或 x^2；支持四则运算、分数和幂。超出范围会提示，不会静默丢失。')
    basis = forms.CharField(label='答案依据／复算说明',widget=forms.Textarea,max_length=4000)
    fallback_region = forms.ChoiceField(label='公式图片回退（选题目来源区域）',required=False,choices=[])
    fallback_alt = forms.CharField(label='图片公式文字说明',required=False,max_length=2000)
    context = forms.CharField(widget=forms.HiddenInput)
    request_key = forms.CharField(widget=forms.HiddenInput)


def _households(actor):
    return list(Household.objects.filter(memberships__user=actor,memberships__user__is_active=True).order_by('pk'))


def _signed(row, purpose, context):
    return records.sign_context(row.entity.household_id,'question',row.pk,purpose,context)


@login_required
@require_http_methods(['GET','POST'])
@transaction.atomic
def index(request):
    houses=_households(request.user)
    choices=[(h.pk,str(h.pk)) for h in houses]
    selected=request.POST.get('household') if request.method=='POST' else request.GET.get('household')
    selected=selected or (houses[0].pk if houses else None)
    questions=[];snapshots=[]
    if selected:
        try: records.household(request.user,selected)
        except (ObjectDoesNotExist,core.PersistenceError):raise Http404
        questions=list(EntityRecord.objects.filter(household_id=selected,kind='question',published_revision__isnull=False)
            .select_related('published_revision').order_by('pk'))
        snapshots=list(ExportSnapshot.objects.filter(household_id=selected).order_by('-pk')[:50])
    form=PrintForm(request.POST or None,initial={'household':selected})
    form.fields['household'].choices=choices
    form.fields['questions'].choices=[(q.published_revision_id,q.published_revision.payload['working_text'][:100]) for q in questions]
    if request.method=='POST' and form.is_valid():
        try:
            snapshot=services.export_questions(request.user,form.cleaned_data['household'],
                form.cleaned_data['questions'],title=form.cleaned_data['title'],purpose=form.cleaned_data['purpose'])
            return redirect('printing:snapshot',pk=snapshot.pk)
        except (core.PersistenceError,ExportError) as exc:form.add_error(None,str(exc))
    return render(request,'printing/index.html',{'form':form,'questions':questions,'snapshots':snapshots})


@login_required
@require_GET
@transaction.atomic
def snapshot(request,pk):
    try:
        row=ExportSnapshot.objects.get(pk=pk)
        records.household(request.user,row.household_id)
    except (ObjectDoesNotExist,core.PersistenceError):raise Http404
    from app.operations.services import snapshot_availability
    return render(request,'printing/snapshot.html',{'snapshot':row,
        'availability':snapshot_availability(request.user,pk)})


@login_required
@require_GET
def download(request,pk,name):
    try:path=services.snapshot_file(request.user,pk,name)
    except ObjectDoesNotExist:raise Http404
    except (core.PersistenceError,ExportError) as exc:
        if exc.code=='snapshot_retired':
            return render(request,'web/message.html',{'title':'导出已退役',
                'message':'此导出文件已按本地策略退役，来源版本及退役账本仍保留。'},status=410)
        return _failure(request,exc)
    return FileResponse(path.open('rb'),as_attachment=True,filename=name)


@login_required
@require_http_methods(['GET','POST'])
@transaction.atomic
def answer(request,pk):
    try:
        row=RevisionRecord.objects.select_related('entity').get(pk=pk,entity__kind='question')
        records.household(request.user,row.entity.household_id)
        services.published_question(row.entity.household_id,row.pk)
    except ObjectDoesNotExist:raise Http404
    except core.PersistenceError as exc:return _failure(request,exc)
    context=services.answer_context(row)
    current=TeacherAnswerRevision.objects.filter(question_revision=row).order_by('-revision_no').first()
    form=AnswerForm(request.POST or None,initial={'body':current.body if current else '',
        'formulas':'',
        'basis':current.basis if current else '', 'context':_signed(row,'answer',context),'request_key':uuid4().hex})
    form.fields['fallback_region'].choices=[('','不使用图片回退')]+[(r['region_revision_id'],f"区域 {n}")
        for n,r in enumerate(row.payload['evidence_refs'],1) if r.get('region_revision_id')]
    if request.method=='POST':
        try:
            expected=records.read_context(request.POST.get('context',''),row.entity.household_id,'question',row.pk,'answer')
            if request.POST.get('action') in {'accepted','rejected','withdrawn'}:
                services.review_answer(request.user,int(request.POST['answer_id']),action=request.POST['action'],
                    reason=request.POST.get('reason',''),expected=expected,request_key=request.POST['request_key'])
                return redirect('printing:answer',pk=pk)
            if form.is_valid():
                if form.cleaned_data['fallback_region']:
                    formulas=[services.source_formula_image(request.user,row.entity.household_id,row.pk,
                        form.cleaned_data['fallback_region'],form.cleaned_data['fallback_alt'])]
                else:formulas=[formula_ast(line) for line in form.cleaned_data['formulas'].splitlines() if line.strip()]
                if current and not formulas:formulas=current.formulas
                services.save_answer(request.user,row.entity.household_id,row.pk,body=form.cleaned_data['body'],formulas=formulas,
                    basis=form.cleaned_data['basis'],expected=expected,request_key=form.cleaned_data['request_key'],
                    confirm=request.POST.get('action')=='save_confirm')
                return redirect('printing:answer',pk=pk)
        except (ValueError,KeyError,ExportError) as exc:form.add_error(None,str(exc))
        except core.PersistenceError as exc:return _failure(request,exc)
    return render(request,'printing/answer.html',{'form':form,'question':row,'current':current,
        'review_context':_signed(row,'answer',context),'request_key':uuid4().hex,
        'history':TeacherAnswerRevision.objects.filter(question_revision=row).prefetch_related('decisions').order_by('-revision_no')})


@login_required
@require_http_methods(['GET','POST'])
@transaction.atomic
def erratum(request,pk):
    try:
        row=RevisionRecord.objects.select_related('entity').get(pk=pk,entity__kind='question')
        records.household(request.user,row.entity.household_id)
    except ObjectDoesNotExist:raise Http404
    except core.PersistenceError as exc:return _failure(request,exc)
    if request.method=='POST':
        try:
            expected=records.read_context(request.POST.get('context',''),row.entity.household_id,'question',row.pk,'erratum')
            if request.POST.get('action')=='apply':
                services.apply_erratum(request.user,row.entity.household_id,request.POST['revision_id'],expected=expected,
                    request_key=request.POST['request_key'])
            elif request.POST.get('action') in {'accept','reject','withdraw'}:
                revision=RevisionRecord.objects.get(pk=request.POST['revision_id'],entity__household_id=row.entity.household_id,entity__kind='erratum')
                review_context=records.read_context(request.POST.get('review_context',''),row.entity.household_id,
                    'erratum',revision.entity.stable_id,'review')
                records.review(request.user,row.entity.household_id,'erratum',revision.entity.stable_id,revision.pk,
                    action=request.POST['action'],reason=request.POST.get('reason',''),context=review_context,request_key=request.POST['request_key'])
            else:
                services.save_erratum(request.user,row.entity.household_id,row.pk,corrected_text=request.POST.get('corrected_text',''),
                    basis=request.POST.get('basis',''),expected=expected,request_key=request.POST['request_key'])
            return redirect('printing:erratum',pk=pk)
        except ObjectDoesNotExist:raise Http404
        except core.PersistenceError as exc:return _failure(request,exc)
    errata=[]
    for e in EntityRecord.objects.filter(household_id=row.entity.household_id,kind='erratum').select_related('head_revision'):
        revision=e.head_revision
        if revision.payload['target_revision_id']!=row.pk:continue
        c=core.review_context(request.user,row.entity.household_id,revision.pk)
        errata.append({'revision':revision,'context':records.sign_context(row.entity.household_id,'erratum',e.stable_id,'review',c),
            'state':revision.review_projection.state,'request_key':uuid4().hex})
    return render(request,'printing/erratum.html',{'question':row,'errata':errata,'request_key':uuid4().hex,
        'context':_signed(row,'erratum',records.edit_context(row))})


@login_required
@require_http_methods(['GET','POST'])
def arithmetic(request):
    result=None;error=None
    if request.method=='POST':
        try:result=check_arithmetic(request.POST.get('expression',''),request.POST.get('expected') or None)
        except ArithmeticError as exc:error=str(exc)
    return render(request,'printing/arithmetic.html',{'result':result,'error':error})


@login_required
@require_http_methods(['GET','POST'])
def evidence_report(request,pk):
    try:
        learner=EntityRecord.objects.get(pk=pk,kind='learner')
        with transaction.atomic():records.household(request.user,learner.household_id)
    except (ObjectDoesNotExist,core.PersistenceError):raise Http404
    error=None
    if request.method=='POST':
        try:
            exported=services.export_evidence_report(request.user,pk)
            return redirect('printing:snapshot',pk=exported.pk)
        except (core.PersistenceError,ExportError) as exc:error=str(exc)
    return render(request,'printing/evidence_report.html',{'learner':learner,'error':error})
