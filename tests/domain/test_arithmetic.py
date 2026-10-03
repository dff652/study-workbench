import unittest
from app.domain.arithmetic import ArithmeticError,check_arithmetic,formula_ast


class ArithmeticTests(unittest.TestCase):
    def test_exact_fraction_and_comparison(self):
        self.assertEqual(check_arithmetic('1/3+1/6','1/2')['matches'],True)
        self.assertEqual(check_arithmetic('0.1+0.2')['result'],'3/10')
        self.assertEqual(check_arithmetic('0.123456789123456789')['result'],'123456789123456789/1000000000000000000')
        self.assertEqual(check_arithmetic('(2/3)^-2')['result'],'9/4')
        self.assertFalse(check_arithmetic('2+2','5')['matches'])

    def test_reject_calls_variables_division_zero_and_unbounded_powers(self):
        for expression in ['__import__("os").system("id")','x+1','1/0','2^100000','[1][0]','True','10'*300]:
            with self.assertRaises(ArithmeticError):check_arithmetic(expression)
        with self.assertRaises(ArithmeticError):formula_ast('f(x)')

    def test_fraction_formula_is_native_and_symbolic_check_is_separate(self):
        self.assertEqual(formula_ast('x/2'),['f',['t','x'],['t','2']])
        self.assertEqual(formula_ast('x^2'),['u',['t','x'],['t','2']])

    def test_power_bases_preserve_unary_and_nested_power_grouping(self):
        self.assertEqual(formula_ast('(-2)^2'),
            ['u',['r',['t','('],['r',['t','-'],['t','2']],['t',')']],['t','2']])
        self.assertEqual(formula_ast('(-x)^2'),
            ['u',['r',['t','('],['r',['t','-'],['t','x']],['t',')']],['t','2']])
        self.assertEqual(formula_ast('(x^2)^3'),
            ['u',['r',['t','('],['u',['t','x'],['t','2']],['t',')']],['t','3']])
        self.assertEqual(formula_ast('-x^2'),['r',['t','-'],['u',['t','x'],['t','2']]])
