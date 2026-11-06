import ast
import pytest

# Le funzioni pure non dipendono da Qt: le estraggo dal sorgente senza importare PyQt6.
SRC = open("frontend/ui/HexDecConverterDialog.py", encoding="utf-8").read()
_ns = {}
for node in ast.parse(SRC).body:
    if isinstance(node, ast.FunctionDef):
        exec(compile(ast.Module([node], []), "hexdec", "exec"), _ns)
parse_int, format_hex, format_bin = _ns["parse_int"], _ns["format_hex"], _ns["format_bin"]


@pytest.mark.parametrize(
    "text,base,expected",
    [
        ("0xFF", 16, 255),
        ("1f", 16, 31),
        ("-0x10", 16, -16),
        ("-10", 10, -10),
        ("0b101", 2, 5),
        ("1111_0000", 2, 240),
        (" 1 000 ", 10, 1000),
    ],
)
def test_parse_valid(text, base, expected):
    assert parse_int(text, base) == expected


@pytest.mark.parametrize("text,base", [("zz", 16), ("", 10), ("--1", 10), ("0x", 16), ("12", 2)])
def test_parse_invalid(text, base):
    with pytest.raises(ValueError):
        parse_int(text, base)


def test_format():
    assert format_hex(255) == "0xFF" and format_hex(-16) == "-0x10"
    assert format_bin(5) == "0b101" and format_bin(-5) == "-0b101"
