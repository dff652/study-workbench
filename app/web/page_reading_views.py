"""Manual whole-page reading and partition inventory, available with AI disabled."""
from uuid import uuid4

from django import forms
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from app.persistence import services as core
from . import page_reading, records, services
from .views import LOGIN_URL, _failure, _not_found


class PageReadingForm(forms.Form):
    reading = forms.ChoiceField(label='阅读状态', choices=(('unread', '未阅读'), ('read', '已阅读'), ('needs_retake', '待重拍')))
    coverage = forms.ChoiceField(label='分区核对', choices=(('partial', '待补分区'), ('complete', '已逐项核对分区')))
    pending_items = forms.CharField(label='待补事项／重拍原因', required=False, max_length=4000, widget=forms.Textarea(attrs={'rows': 3}))
    basis = forms.CharField(label='本次阅读与分区依据', max_length=1000, widget=forms.Textarea(attrs={'rows': 2}))
    sources = forms.JSONField(required=False, widget=forms.HiddenInput)
    context_token = forms.CharField(widget=forms.HiddenInput)
    request_key = forms.CharField(max_length=160, widget=forms.HiddenInput)

    def clean_sources(self):
        value = self.cleaned_data['sources']
        return [] if value is None else value


@_not_found
@login_required(login_url=LOGIN_URL)
@require_http_methods(['GET', 'POST'])
@never_cache
def reading(request, page_id):
    try:
        data = page_reading.detail(request.user, page_id)
        page = data['page']
        owner = page.material.household_id
        token = records.sign_context(owner, 'page', str(page_id), 'page-reading', data['context'])
        current = data['history'][0] if data['history'] else None
        sources = [{key: part[key] for key in ('kind', 'page_id', 'rotation', 'preview_sha256', 'display_bbox')}
            for part in current.partitions] if current else []
        if request.method == 'POST':
            if not data['writable']:
                raise core.PersistenceError('permission_denied', '无权保存整页状态。')
            form = PageReadingForm(request.POST)
            if form.is_valid():
                expected = records.read_context(form.cleaned_data['context_token'], owner,
                    'page', str(page_id), 'page-reading')
                page_reading.save(request.user, page_id, expected=expected,
                    **{key: value for key, value in form.cleaned_data.items() if key != 'context_token'})
                return redirect('web:page_reading', page_id=page_id)
        else:
            form = PageReadingForm(initial={'reading': current.reading if current else 'unread',
                'coverage': current.coverage if current else 'partial', 'sources': sources,
                'pending_items': current.pending_items if current else '',
                'context_token': token, 'request_key': uuid4().hex})
        for row in data['history']:
            row.display_parts = [{'label': page_reading.KINDS[part['kind']], **part} for part in row.partitions]
        previews = [services.preview_file(request.user, page_id, angle) for angle in (0, 90, 180, 270)]
        preview = previews[0]
        return render(request, 'web/page_reading.html', {**data, 'form': form,
            'current': current, 'kinds': page_reading.KINDS.items(), 'preview': preview,
            'preview_url': reverse('web:page_preview', kwargs={'page_id': page_id, 'rotation': 0}),
            'preview_links': [{'rotation': row.rotation, 'width': row.width, 'height': row.height,
                'sha256': row.sha256, 'url': reverse('web:page_preview', kwargs={'page_id': page_id, 'rotation': row.rotation})}
                for row in previews]}, status=400 if request.method == 'POST' else 200)
    except core.PersistenceError as exc:
        return _failure(request, exc)
