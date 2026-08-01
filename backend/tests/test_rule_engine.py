"""规则引擎 DSL 解析与求值单元测试（D07 测试设计）。

覆盖：
- DSL 语法：比较 / && / || / 括号优先级 / 括号不匹配
- 求值语义：数字比较、字符串比较、缺失字段、类型不匹配
- 非法语法：_DslSyntaxError
"""

from __future__ import annotations

import pytest

from app.services.rule_engine import (
    _CmpExpr,
    _DslSyntaxError,
    _parse_expression,
    _tokenize,
)


def _eval(dsl: str, tx: dict) -> bool:
    return _parse_expression(dsl).evaluate(tx)


class TestTokenize:
    def test_numbers_and_operators(self) -> None:
        tokens = _tokenize('amount > 1000000 && tx_type == "WITHDRAW"')
        kinds = [k for k, _ in tokens]
        assert kinds == [
            "field", "op", "num", "op",
            "field", "op", "str",
        ]

    def test_parentheses(self) -> None:
        tokens = _tokenize("(a > 1 || b < 2) && c != 3")
        assert ("op", "(") in tokens
        assert ("op", ")") in tokens

    def test_unknown_symbol_raises(self) -> None:
        with pytest.raises(_DslSyntaxError):
            _tokenize("amount @ 100")


class TestComparison:
    def test_numeric_greater(self) -> None:
        assert _eval("amount > 1000000", {"amount": 2000000}) is True
        assert _eval("amount > 1000000", {"amount": 500000}) is False

    def test_numeric_comparisons(self) -> None:
        tx = {"amount": 100}
        assert _eval("amount >= 100", tx) is True
        assert _eval("amount == 100", tx) is True
        assert _eval("amount != 99", tx) is True
        assert _eval("amount <= 99", tx) is False

    def test_string_equality(self) -> None:
        tx = {"tx_type": "WITHDRAW"}
        assert _eval('tx_type == "WITHDRAW"', tx) is True
        assert _eval('tx_type != "PURCHASE"', tx) is True

    def test_missing_field_returns_false(self) -> None:
        assert _eval("amount > 100", {"tx_type": "WITHDRAW"}) is False

    def test_type_mismatch_returns_false(self) -> None:
        # int vs str 比较不命中
        assert _eval("amount > 100", {"amount": "abc"}) is False


class TestLogicalOperators:
    def test_and(self) -> None:
        dsl = 'amount > 1000 && tx_type == "WITHDRAW"'
        assert _eval(dsl, {"amount": 2000, "tx_type": "WITHDRAW"}) is True
        assert _eval(dsl, {"amount": 2000, "tx_type": "PURCHASE"}) is False

    def test_or(self) -> None:
        dsl = 'amount > 1000 || tx_type == "WITHDRAW"'
        assert _eval(dsl, {"amount": 10, "tx_type": "WITHDRAW"}) is True
        assert _eval(dsl, {"amount": 10, "tx_type": "PURCHASE"}) is False

    def test_precedence_and_over_or(self) -> None:
        # a || b && c 应解析为 a || (b && c)
        dsl = 'a == 1 || b == 2 && c == 3'
        assert _eval(dsl, {"a": 0, "b": 2, "c": 3}) is True
        assert _eval(dsl, {"a": 0, "b": 2, "c": 9}) is False
        assert _eval(dsl, {"a": 1, "b": 9, "c": 9}) is True

    def test_parentheses_override_precedence(self) -> None:
        dsl = '(a == 1 || b == 2) && c == 3'
        assert _eval(dsl, {"a": 0, "b": 2, "c": 9}) is False
        assert _eval(dsl, {"a": 1, "b": 9, "c": 3}) is True

    def test_chained_and(self) -> None:
        dsl = "a > 1 && b > 1 && c > 1"
        assert _eval(dsl, {"a": 2, "b": 2, "c": 2}) is True
        assert _eval(dsl, {"a": 2, "b": 2, "c": 0}) is False


class TestSyntaxErrors:
    @pytest.mark.parametrize(
        "dsl",
        [
            "amount >",              # 右侧缺操作数
            "> 100",                 # 左侧缺操作数
            "amount > 100 &&",       # 尾随 &&
            "(amount > 100",         # 括号未闭合
            "amount > 100)",         # 多余右括号
            "",                      # 空表达式
            "amount",                # 无比较运算符
        ],
    )
    def test_invalid_dsl_raises(self, dsl: str) -> None:
        with pytest.raises(_DslSyntaxError):
            _parse_expression(dsl)


class TestExprTree:
    def test_cmp_expr_builds(self) -> None:
        expr = _CmpExpr("amount", ">", 100)
        assert expr.evaluate({"amount": 101}) is True
        assert expr.evaluate({"amount": 100}) is False
