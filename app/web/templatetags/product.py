from django import template
from app.web.presentation import ui_label

register = template.Library()
register.filter("ui_label", ui_label)


@register.filter
def ui_labels(values):
    return "、".join(ui_label(value) for value in values) if values else "无"
