"""Server-validated forms for the manual knowledge map."""
from django import forms

from .forms import RequestForm, ReviewForm


NODE_KINDS = (
    ("knowledge", "知识点"),
    ("method", "方法"),
    ("question_type", "题型"),
)


class IndexForm(forms.Form):
    household_id = forms.ChoiceField(label="家庭", choices=())
    knowledge_id = forms.ChoiceField(label="知识点", required=False, choices=(("", "全部"),))
    method_id = forms.ChoiceField(label="方法", required=False, choices=(("", "全部"),))
    question_type_id = forms.ChoiceField(label="题型", required=False, choices=(("", "全部"),))
    review = forms.ChoiceField(label="题目审核", required=False, choices=(
        ("", "全部"), ("draft", "待审核"), ("accepted", "已审核"),
        ("rejected", "已退回"), ("stale", "依赖已变化"),
    ))
    number = forms.CharField(label="题号文本", required=False, max_length=80)

    def __init__(self, *args, households=(), household_id="", nodes=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["household_id"].choices = [(str(row.household_id), str(row.household.id)) for row in households]
        if household_id:
            for kind, field in (("knowledge", "knowledge_id"), ("method", "method_id"),
                                ("question_type", "question_type_id")):
                rows = (nodes or {}).get(kind, ())
                choices = [("", "全部")] + [
                    (row["stable_id"], row["name"]) for row in rows
                ]
                self.fields[field].choices = choices


class ScopedRequestForm(RequestForm):
    household_id = forms.CharField(widget=forms.HiddenInput)
    context_token = forms.CharField(required=False, widget=forms.HiddenInput)
    reason = forms.CharField(max_length=1000, label="本次修订说明", widget=forms.Textarea(attrs={"rows": 3}))


class KnowledgeForm(ScopedRequestForm):
    definition = forms.CharField(max_length=20000, label="定义、公式与例题", widget=forms.Textarea(attrs={"rows": 12}),
        help_text="完整写入定义、公式、示例和推导；数学表达式按原样保留。")
    conditions = forms.CharField(required=False, max_length=6000, label="适用条件", widget=forms.Textarea(attrs={"rows": 5}),
        help_text="每行一项。")
    common_errors = forms.CharField(required=False, max_length=6000, label="易错点", widget=forms.Textarea(attrs={"rows": 5}),
        help_text="每行一项。")
    sources = forms.CharField(required=False, widget=forms.HiddenInput, initial="[]")
    replace_sources = forms.BooleanField(required=False, label="用本次选择替换当前来源")


class MethodForm(ScopedRequestForm):
    name = forms.CharField(max_length=200, label="方法名称")
    parent_revision_id = forms.ChoiceField(required=False, label="上级方法（精确版本）", choices=(("", "无上级"),))
    conditions = forms.CharField(required=False, max_length=6000, label="适用条件", widget=forms.Textarea(attrs={"rows": 4}),
        help_text="每行一项。")
    steps = forms.CharField(required=False, max_length=12000, label="步骤", widget=forms.Textarea(attrs={"rows": 8}),
        help_text="每行一步；可以包含完整数学表达式。")
    notes = forms.CharField(required=False, max_length=6000, label="备注", widget=forms.Textarea(attrs={"rows": 4}),
        help_text="每行一项。")
    sources = forms.CharField(required=False, widget=forms.HiddenInput, initial="[]")
    replace_sources = forms.BooleanField(required=False, label="用本次选择替换当前来源")

    def __init__(self, *args, parent_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parent_revision_id"].choices = [("", "无上级")] + list(parent_choices)


class QuestionTypeForm(ScopedRequestForm):
    name = forms.CharField(max_length=200, label="题型名称")
    structural_features = forms.CharField(required=False, max_length=6000, label="结构特征", widget=forms.Textarea(attrs={"rows": 5}),
        help_text="每行一项。")
    conditions = forms.CharField(required=False, max_length=6000, label="适用条件", widget=forms.Textarea(attrs={"rows": 5}),
        help_text="每行一项。")
    sources = forms.CharField(required=False, widget=forms.HiddenInput, initial="[]")
    replace_sources = forms.BooleanField(required=False, label="用本次选择替换当前来源")


class LinkForm(ScopedRequestForm):
    kind = forms.ChoiceField(label="节点类型", choices=NODE_KINDS)
    node_revision_id = forms.ChoiceField(label="节点精确版本", choices=())
    question_revision_id = forms.ChoiceField(label="题目精确版本", choices=())
    role = forms.ChoiceField(label="关系", choices=(
        ("applies", "知识点：适用于题目"), ("primary", "方法：主方法"),
        ("auxiliary", "方法：辅助方法"), ("belongs", "题型：归属题型"),
    ))

    def __init__(self, *args, node_choices=(), question_choices=(), forced_kind=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["node_revision_id"].choices = list(node_choices)
        self.fields["question_revision_id"].choices = list(question_choices)
        if forced_kind:
            self.fields["kind"].initial = forced_kind
            self.fields["kind"].widget = forms.HiddenInput()
            self.fields["kind"].choices = [(forced_kind, dict(NODE_KINDS)[forced_kind])]
            role_choices = {
                "knowledge": (("applies", "适用于题目"),),
                "method": (("primary", "主方法"), ("auxiliary", "辅助方法")),
                "question_type": (("belongs", "归属题型"),),
            }
            self.fields["role"].choices = role_choices[forced_kind]

    def clean(self):
        cleaned = super().clean()
        expected_role = {"knowledge": "applies", "method": None, "question_type": "belongs"}
        kind, role = cleaned.get("kind"), cleaned.get("role")
        if kind in expected_role and expected_role[kind] and role != expected_role[kind]:
            self.add_error("role", "关系类型与所选节点不匹配。")
        if kind == "method" and role not in {"primary", "auxiliary"}:
            self.add_error("role", "方法关联请选择主方法或辅助方法。")
        return cleaned


class NodeReviewForm(ReviewForm):
    def __init__(self, *args, actions=None, **kwargs):
        super().__init__(*args, **kwargs)
        if actions is not None:
            labels = dict(ReviewForm.ACTIONS)
            self.fields["action"].choices = [("", "请选择")] + [(value, labels[value]) for value in actions]
