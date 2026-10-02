"""Bounded decoding and quarter-turn mappings; original upload bytes never change."""
import hashlib
import io
import math
import warnings
from PIL import Image
from app.persistence.services import PersistenceError

MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 16_000_000
ROTATIONS = (0, 90, 180, 270)


def uploaded_bytes(upload):
    raw = bytearray()
    for chunk in upload.chunks():
        raw.extend(chunk)
        if len(raw) > MAX_UPLOAD_BYTES:
            raise PersistenceError('upload_too_large', '照片超过 12 MiB 上限。')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw), formats=['JPEG','PNG']) as image:
                if image.width*image.height > MAX_PIXELS or getattr(image,'n_frames',1) != 1:
                    raise PersistenceError('invalid_image', '照片像素超限或包含多帧。')
                image.verify()
            with Image.open(io.BytesIO(raw), formats=['JPEG','PNG']) as image:
                image.load()
                return bytes(raw), image.format, image.width, image.height
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise PersistenceError('invalid_image', '文件不是可完整解码的 JPEG 或 PNG。') from exc


def preview_bytes(raw, rotation):
    with Image.open(io.BytesIO(raw)) as source:
        # Paste onto a fresh canvas so EXIF orientation and identifying metadata
        # cannot alter the preview's intrinsic pixel coordinate space.
        rgba = source.convert('RGBA')
        image = Image.new('RGB', source.size, 'white')
        image.paste(rgba, mask=rgba.getchannel('A'))
    image = image.rotate(-rotation, expand=True)
    output = io.BytesIO()
    image.save(output, format='PNG')
    return output.getvalue(), image.width, image.height


def original_bbox(box, width, height, rotation):
    if rotation not in ROTATIONS or not isinstance(box,(list,tuple)) or len(box)!=4:
        raise PersistenceError('invalid_region', '区域或旋转角度无效。')
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in box):
        raise PersistenceError('invalid_region', '区域坐标必须是有限数值。')
    x0,y0,x1,y1 = box
    display_width,display_height = (height,width) if rotation in (90,270) else (width,height)
    if not (0<=x0<x1<=display_width and 0<=y0<y1<=display_height):
        raise PersistenceError('invalid_region', '框选区域超出图片或为空。')
    def inverse(x,y):
        return {0:(x,y),90:(y,height-x),180:(width-x,height-y),270:(width-y,x)}[rotation]
    points=[inverse(x,y) for x in (x0,x1) for y in (y0,y1)]
    return (min(p[0] for p in points),min(p[1] for p in points),max(p[0] for p in points),max(p[1] for p in points))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()
