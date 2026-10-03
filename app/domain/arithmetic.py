"""Bounded rational arithmetic and printable formula syntax; never Python eval.

Arithmetic is an exact check of a supplied expression, not a proof, OCR
correction or a judgment about a learner. Symbolic leaves can be printed but
are deliberately outside the deterministic arithmetic checker.
"""
import ast
import re
from fractions import Fraction


class ArithmeticError(ValueError):
    pass


def _parse(expression):
    if not isinstance(expression,str) or not expression.strip() or len(expression)>512:
        raise ArithmeticError('表达式须为 1～512 个字符。')
    source=expression.replace('^','**')
    try: tree=ast.parse(source,mode='eval')
    except (SyntaxError,ValueError,RecursionError) as exc: raise ArithmeticError('表达式语法不支持。') from exc
    if len(list(ast.walk(tree)))>64:raise ArithmeticError('表达式超出复杂度限制。')
    for node in ast.walk(tree):
        if isinstance(node,ast.Constant):node._numeric_text=ast.get_source_segment(source,node)
    return tree.body


def _number(node):
    if not isinstance(node,ast.Constant) or type(node.value) not in (int,float):
        raise ArithmeticError('复算只支持有理数及四则运算、有限整数幂。')
    text=getattr(node,'_numeric_text',str(node.value))
    if len(text)>80 or not re.fullmatch(r'(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,3})?',text):
        raise ArithmeticError('只支持有限十进制数。')
    if 'e' in text.lower() and abs(int(text.lower().split('e')[1]))>100:
        raise ArithmeticError('数值超出范围。')
    value=Fraction(text)
    if max(value.numerator.bit_length(),value.denominator.bit_length())>512:
        raise ArithmeticError('数值超出范围。')
    return value


def _calculate(node):
    if isinstance(node,ast.Constant):return _number(node)
    if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
        value=_calculate(node.operand)
        return -value if isinstance(node.op,ast.USub) else value
    if not isinstance(node,ast.BinOp):raise ArithmeticError('不支持变量、函数调用或其他操作。')
    left,right=_calculate(node.left),_calculate(node.right)
    if isinstance(node.op,ast.Add):value=left+right
    elif isinstance(node.op,ast.Sub):value=left-right
    elif isinstance(node.op,ast.Mult):value=left*right
    elif isinstance(node.op,ast.Div):
        if not right:raise ArithmeticError('除数不能为零。')
        value=left/right
    elif isinstance(node.op,ast.Pow):
        if right.denominator!=1 or not -10<=right.numerator<=10:raise ArithmeticError('幂指数只支持 -10～10 的整数。')
        if not left and right<0:raise ArithmeticError('零不能取负整数幂。')
        value=left**right.numerator
    else:raise ArithmeticError('仅支持 +、-、*、/ 和整数幂。')
    if max(value.numerator.bit_length(),value.denominator.bit_length())>512:raise ArithmeticError('数值超出范围。')
    return value


def check_arithmetic(expression, expected=None):
    value=_calculate(_parse(expression))
    matches=None if expected is None else value==_calculate(_parse(expected))
    return {'expression':expression,'numerator':value.numerator,'denominator':value.denominator,
        'result':str(value),'matches':matches,'scope':'有理数四则运算及 -10～10 整数幂；不判定掌握或一般恒等式'}


def formula_ast(expression):
    def visit(node):
        if isinstance(node,ast.Constant):
            _number(node);return ['t',getattr(node,'_numeric_text',str(node.value))]
        if isinstance(node,ast.Name) and node.id.isascii() and len(node.id)<=20:return ['t',node.id]
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,(ast.UAdd,ast.USub)):
            return ['r',['t','-' if isinstance(node.op,ast.USub) else '+'],visit(node.operand)]
        if isinstance(node,ast.BinOp):
            left,right=visit(node.left),visit(node.right)
            if isinstance(node.op,ast.Div):return ['f',left,right]
            if isinstance(node.op,ast.Pow):
                if (isinstance(node.left,ast.UnaryOp) or
                    (isinstance(node.left,ast.BinOp) and isinstance(node.left.op,ast.Pow))):
                    left=['r',['t','('],left,['t',')']]
                return ['u',left,right]
            operators={ast.Add:'+',ast.Sub:'-',ast.Mult:'×'}
            if type(node.op) in operators:
                return ['r',['t','('],left,['t',operators[type(node.op)]],right,['t',')']]
        raise ArithmeticError('公式超出原生支持范围，请使用可追溯的公式图片回退。')
    return visit(_parse(expression))
