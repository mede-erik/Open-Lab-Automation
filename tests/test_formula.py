# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Safe formulas: they compute, they refuse everything that is not arithmetic."""

import pytest

from ola.formula import Formula, FormulaError


def ev(text, **values):
    return Formula(text).evaluate(values)


def test_arithmetic_and_precedence():
    assert ev("1 + 2 * 3") == 7
    assert ev("(1 + 2) * 3") == 9
    assert ev("2 ** 3 ** 2") == 512  # right associative, like Python
    assert ev("-a + +b", a=2, b=5) == 3
    assert ev("10 / 4") == 2.5


def test_efficiency_example_with_at_names_and_derived_names():
    f = Formula("100 * pout / pin")
    assert f.names == {"pout", "pin"}
    assert f.evaluate({"pout": 8.5, "pin": 10}) == pytest.approx(85.0)
    g = Formula("vin@daq * iin@daq - vin")
    assert g.names == {"vin@daq", "iin@daq", "vin"}
    assert g.evaluate({"vin@daq": 12.0, "iin@daq": 2.0, "vin": 12.0}) == pytest.approx(12.0)


def test_functions():
    assert ev("sqrt(16) + abs(-2)") == 6
    assert ev("max(1, 5, 3) - min(4, 2)") == 3
    assert ev("log10(1000)") == pytest.approx(3.0)
    assert ev("exp(0)") == 1


@pytest.mark.parametrize(
    "text,values",
    [
        ("a / b", {"a": 1, "b": 0}),  # division by zero
        ("a + b", {"a": 1}),  # a missing value
        ("a + b", {"a": 1, "b": None}),  # a value that could not be measured
        ("sqrt(a)", {"a": -1}),  # out of domain
        ("log(a)", {"a": 0}),
        ("9 ** 9 ** 9", {}),  # overflow
        ("a", {"a": True}),  # a boolean is not a measurement
        ("a", {"a": "5"}),
    ],
)
def test_values_that_cannot_be_computed_give_none(text, values):
    assert Formula(text).evaluate(values) is None


@pytest.mark.parametrize(
    "text,message",
    [
        ("", "empty"),
        ("   ", "empty"),
        ("1 +", "syntax error"),
        ("a b", "syntax error"),
        ("a @ b", "'@' must join"),
        ("vin@", "'@' must join"),
        ("@daq", "'@' must join"),
        ("a % b", "and \\*\\* are allowed"),
        ("a // b", "and \\*\\* are allowed"),
        ("not a", "only the signs"),
        ("~a", "only the signs"),
        ("a if b else c", "only arithmetic"),
        ("a < b", "only arithmetic"),
        ("[a, b]", "only arithmetic"),
        ("'text'", "only numbers"),
        ("True", "only numbers"),
        ("1j", "only numbers"),
        ("__import__('os')", "two underscores"),
        ("a.real", "only arithmetic"),
        ("a[0]", "only arithmetic"),
        ("open('x')", "unknown function"),
        ("print(a)", "unknown function"),
        ("(lambda: 1)()", "only arithmetic|unknown function"),
        ("sqrt", "is a function"),
        ("sqrt()", "takes plain values"),
        ("max(a, key=b)", "takes plain values"),
        ("x" * 600, "too long"),
    ],
)
def test_everything_that_is_not_arithmetic_is_refused(text, message):
    with pytest.raises(FormulaError, match=message):
        Formula(text)


def test_nothing_from_the_formula_reaches_the_interpreter(tmp_path):
    marker = tmp_path / "pwned"
    for text in (f"__import__('os').system('touch {marker}')", f"open('{marker}', 'w')"):
        with pytest.raises(FormulaError):
            Formula(text)
    assert not marker.exists()
