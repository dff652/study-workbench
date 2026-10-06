from django import template
from app.web.presentation import ui_label

register = template.Library()
register.filter("ui_label", ui_label)


@register.filter
def ui_labels(values):
    return "、".join(ui_label(value) for value in values) if values else "无"


@register.filter
def local_timestamp(value):
    """A recorded timestamp is not an actual learning date."""
    from datetime import datetime
    from django.utils import timezone
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return value
    if not isinstance(value, datetime):
        return value or '未记录'
    if timezone.is_aware(value):
        from zoneinfo import ZoneInfo
        value = timezone.localtime(value, ZoneInfo("Asia/Shanghai"))
        return value.strftime('%Y-%m-%d %H:%M:%S UTC%z')
    return value.strftime('%Y-%m-%d %H:%M:%S') + '（时区未记录）'


@register.simple_tag
def frontend_formula_assets():
    """Reuse the built formula component in authenticated legacy forms."""
    import re
    from django.utils.html import format_html_join
    from app.api.views import frontend_root
    index = frontend_root() / 'index.html'
    if not index.is_file():
        return ''
    content = index.read_text(encoding='utf-8')
    scripts = re.findall(r'src="(/app/assets/[A-Za-z0-9_.-]+\.js)"', content)
    styles = re.findall(r'href="(/app/assets/[A-Za-z0-9_.-]+\.css)"', content)
    return format_html_join('', '<link rel="stylesheet" href="{}">', ((url,) for url in styles)) + format_html_join('', '<script type="module" src="{}"></script>', ((url,) for url in scripts))
