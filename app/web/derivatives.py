"""Explicit local crop, manual masking and contrast; no text reconstruction."""
import io
import math
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.db import transaction
from PIL import Image, ImageDraw, ImageEnhance

from app.exports.snapshots import private_directory, write_private
from app.persistence import services as core
from . import services
from .images import digest, original_bbox
from .models import ImageDerivative


def _box(value,width,height):
    box=original_bbox(value,width,height,0)
    return [math.floor(box[0]),math.floor(box[1]),math.ceil(box[2]),math.ceil(box[3])]


def create_derivative(actor,page_id,*,operation,display_bbox,rotation,preview_sha256,
                      masks=None,contrast=1.5,request_key):
    created=[]
    try:
        # Commit belongs to this operation so a commit failure also cleans its
        # uniquely owned file. Nested callers cannot defer that guarantee.
        with transaction.atomic(durable=True):
            return _create_derivative(actor,page_id,operation=operation,display_bbox=display_bbox,
                rotation=rotation,preview_sha256=preview_sha256,masks=masks,contrast=contrast,
                request_key=request_key,created=created)
    except BaseException:
        for path in created:path.unlink(missing_ok=True)
        raise


def _create_derivative(actor,page_id,*,operation,display_bbox,rotation,preview_sha256,
                       masks,contrast,request_key,created):
    page=services._page(actor,page_id)
    services._household(actor,page.material.household_id,True)
    preview=services.preview_file(actor,page_id,rotation)
    if preview.sha256!=preview_sha256:
        raise core.PersistenceError('preview_changed','预览改变，请重新选择。')
    services.asset_path(preview.storage_key,preview.sha256)
    if operation not in {'crop','erase','contrast'}:
        raise core.PersistenceError('invalid_input','请选择裁切、手动遮白或对比度增强。')
    original=page.image
    width,height=original.payload['width'],original.payload['height']
    box=_box(original_bbox(display_bbox,width,height,rotation),width,height)
    masks=masks or []
    if not isinstance(masks,list) or len(masks)>20 or (operation=='erase' and not masks):
        raise core.PersistenceError('invalid_input','手动遮白须给出 1～20 个原图坐标矩形。')
    boxes=[_box(mask,width,height) for mask in masks]
    if operation!='erase' and boxes:
        raise core.PersistenceError('invalid_input','仅手动遮白操作使用遮白矩形。')
    for x0,y0,x1,y1 in boxes:
        if not (box[0]<=x0<x1<=box[2] and box[1]<=y0<y1<=box[3]):
            raise core.PersistenceError('invalid_input','遮白矩形必须完全位于所选裁切区域内。')
    if type(contrast) not in (int,float) or not math.isfinite(contrast) or not 0.5<=contrast<=3:
        raise core.PersistenceError('invalid_input','对比度须为 0.5～3。')
    request_key=services._text(str(request_key),160)
    parameters={'version':'local-image.v1','display_rotation':rotation,'display_bbox':list(display_bbox),
        'original_bbox':box,'coordinate_space':'original_pixels','masks':boxes,
        'contrast':contrast if operation=='contrast' else None,'output_rotation':0}
    fingerprint=core._digest({'source':original.sha256,'operation':operation,'parameters':parameters})
    existing=ImageDerivative.objects.filter(page=page,created_by=actor,request_key=request_key).first()
    if existing:
        if existing.fingerprint!=fingerprint:raise core.PersistenceError('request_conflict','本次请求已有不同操作。')
        return existing
    path=services.asset_path(original.payload['storage_key'],original.sha256)
    with Image.open(path) as image:
        output=image.convert('RGB').crop(tuple(box))
        if operation=='erase':
            draw=ImageDraw.Draw(output)
            for x0,y0,x1,y1 in boxes:
                draw.rectangle((x0-box[0],y0-box[1],x1-box[0]-1,y1-box[1]-1),fill='white')
        elif operation=='contrast':output=ImageEnhance.Contrast(output).enhance(contrast)
        stream=io.BytesIO();output.save(stream,format='PNG');raw=stream.getvalue()
    sha=digest(raw)
    record_id=uuid4()
    key='derivatives/'+digest(original.household_id.encode())[:24]+'/'+str(record_id)+'-'+sha+'.png'
    destination=Path(settings.SWB_DATA_ROOT)/key
    private_directory(destination.parent)
    created.append(destination)
    try:write_private(destination,raw)
    except FileExistsError:
        created.remove(destination)
        raise
    descriptions={'crop':'裁切舍弃区域外像素；输出保持原图方向。',
        'erase':'手动矩形遮白会永久丢失遮挡区像素，可能同时遮掉印刷文字；不恢复原文。',
        'contrast':'对比度变换可能截断颜色与灰度，不能恢复模糊或遮挡文字。'}
    return ImageDerivative.objects.create(id=record_id,page=page,original_image=original,created_by=actor,
        operation=operation,parameters=parameters,original_sha256=original.sha256,sha256=sha,
        storage_key=key,width=output.width,height=output.height,lossy_description=descriptions[operation],
        request_key=request_key,fingerprint=fingerprint)


@transaction.atomic
def derivative_file(actor,derivative_id):
    row=ImageDerivative.objects.select_related('page','page__material','original_image').get(pk=derivative_id)
    services._page(actor,row.page_id)
    services.asset_path(row.original_image.payload['storage_key'],row.original_sha256)
    return row,services.asset_path(row.storage_key,row.sha256)
