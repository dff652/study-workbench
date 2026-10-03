from django import forms
from .forms import RequestForm


class DerivativeForm(RequestForm):
    operation=forms.ChoiceField(label='处理方式',choices=(('crop','裁切'),('erase','手动矩形遮白'),('contrast','对比度增强')))
    display_bbox=forms.JSONField(label='裁切框（显示坐标）',initial=[0,0,1,1],
        help_text='从上方选择区域后点击“使用最后加入的区域”，或填 [x0,y0,x1,y1]。')
    rotation=forms.TypedChoiceField(label='输入坐标的显示方向',coerce=int,choices=((0,'0°'),(90,'90°'),(180,'180°'),(270,'270°')))
    preview_sha256=forms.CharField(widget=forms.HiddenInput)
    masks=forms.JSONField(label='遮白矩形（原图坐标）',required=False,initial=[],
        help_text='仅遮白使用，最多20个 [[x0,y0,x1,y1],…]。会同时抹去矩形内的印刷内容。')
    contrast=forms.FloatField(label='对比度',initial=1.5,min_value=0.5,max_value=3)
