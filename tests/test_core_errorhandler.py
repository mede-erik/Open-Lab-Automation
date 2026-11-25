# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""frontend.core.errorhandler and the error-code reference (ERROR_CODES.md)."""

import glob
import logging
import os
import re

import pytest

from frontend.core import errorhandler as eh
from frontend.core.errorhandler import ErrorCode, ErrorHandler
from ola.call_errors import CallError, InvalidArgumentError, StepFailedError
from ola.errors import TransportTimeout
from tests.conftest import REPO

DOC = os.path.join(REPO, "ERROR_CODES.md")
CODE = re.compile(r"\b([A-Z]{2,5}-\d{3})\b")


@pytest.fixture
def handler(caplog):
    caplog.set_level(logging.ERROR)
    h = ErrorHandler(logging.getLogger("test.errorhandler"))
    received = []
    h.error_occurred.connect(lambda code, msg: received.append((code, msg)))
    h.received = received
    return h


def test_custom_exception_code_is_logged_and_emitted(handler, caplog):
    exc = eh.FileError(ErrorCode.FILE_NOT_FOUND, "project.json missing")
    handler.handle_error(exc, "Cannot open", show_dialog=False)
    assert handler.received == [("FILE-001", "project.json missing")]
    assert "[FILE-001] project.json missing" in caplog.text


def test_engine_exceptions_keep_their_code(handler):
    handler.handle_error(InvalidArgumentError("bad value", call="x"), show_dialog=False)
    handler.handle_error(TransportTimeout("[TRN-003] no answer"), show_dialog=False)
    step = StepFailedError("read_voltage", 0, TransportTimeout("[TRN-003] no answer"))
    handler.handle_error(step, show_dialog=False)
    codes = [code for code, _ in handler.received]
    assert codes == ["CALL-003", "TRN-003", "CALL-004"]
    assert handler.received[0][1] == "bad value"


def test_a_plain_exception_gets_the_code_given_or_sys_007(handler):
    handler.handle_error(RuntimeError("boom"), show_dialog=False)
    handler.handle_error(RuntimeError("bad"), show_dialog=False, code="PROJ-005")
    handler.handle_error(InvalidArgumentError("x", call="c"), show_dialog=False, code="PROJ-005")
    assert handler.received == [("SYS-007", "boom"), ("PROJ-005", "bad"), ("CALL-003", "x")]


# ---- every message box has a code ---------------------------------------------------------------
def test_show_problem_adds_the_code_once_and_logs(monkeypatch, caplog):
    shown = []
    for kind in ("warning", "critical"):
        monkeypatch.setattr(
            eh.QMessageBox, kind,
            staticmethod(lambda parent, title, text, k=kind: shown.append((k, title, text))),
        )  # fmt: skip
    caplog.set_level(logging.WARNING, logger="frontend.errors")
    eh.show_problem(None, "T", "It failed", code=ErrorCode.MEAS_SAVE_FAILED)
    eh.show_problem(None, "T", "Too much [TOOL-004]", code="TOOL-004", level="critical")
    eh.show_problem(None, "T", "no answer", exception=StepFailedError("x", 0, OSError("t")))
    eh.show_problem(None, "T", "boom", exception=RuntimeError("boom"))
    assert shown[0] == ("warning", "T", "It failed\n\n[MEAS-002]")
    assert shown[1] == ("critical", "T", "Too much [TOOL-004]")  # not twice
    assert shown[2][2].endswith("[CALL-004]") and shown[3][2].endswith("[SYS-007]")
    assert "[MEAS-002] It failed" in caplog.text


def _frontend_calls():
    import ast

    for path in glob.glob(os.path.join(REPO, "frontend", "**", "*.py"), recursive=True):
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                yield os.path.relpath(path, REPO), node


def test_no_message_box_of_a_problem_goes_around_show_problem():
    """A warning or error box must show a code: it goes through errorhandler.show_problem."""
    import ast

    direct = [
        f"{path}:{node.lineno}"
        for path, node in _frontend_calls()
        if ast.unparse(node.func) in ("QMessageBox.warning", "QMessageBox.critical")
        and not path.endswith(os.path.join("core", "errorhandler.py"))
    ]
    assert direct == []


# a failure that comes from a thread as a text: its code is the one written in the text
TEXT_ONLY = {os.path.join("frontend", "ui", "VnaPanel.py")}


def test_every_show_problem_names_its_code_and_it_is_documented():
    import ast

    documented = set(_documented())
    for path, node in _frontend_calls():
        if ast.unparse(node.func) != "show_problem":
            continue
        keywords = {k.arg: k.value for k in node.keywords}
        if path in TEXT_ONLY:
            continue
        assert "code" in keywords or "exception" in keywords, f"{path}:{node.lineno}"
        code = keywords.get("code")
        if isinstance(code, ast.Constant):
            assert code.value in documented, f"{path}:{node.lineno}: {code.value}"


@pytest.mark.parametrize(
    "message,code",
    [
        ("VI_ERROR_RSRC_NFOUND (-1073807343)", "VISA-002"),
        ("Can't connect to server", "VISA-001"),
        ("VI_ERROR_TMO: Timeout expired", "VISA-004"),
        ("something else", "VISA-003"),
    ],
)
def test_visa_errors_are_classified(handler, message, code):
    handler.handle_visa_error(Exception(message), "reading", show_dialog=False)
    assert handler.received[-1][0] == code


def test_ui_errors_are_classified(handler, monkeypatch):
    shown = []
    monkeypatch.setattr(ErrorHandler, "show_error_dialog", lambda self, *a: shown.append(a))
    handler.handle_ui_error(RuntimeError("wrapped C/C++ object of type X has been deleted"))
    handler.handle_ui_error(RuntimeError("other"))
    assert [c for c, _ in handler.received] == ["UI-001", "UI-002"]
    assert len(shown) == 2


def test_show_dialog_is_used_only_when_asked(handler, monkeypatch):
    shown = []
    monkeypatch.setattr(ErrorHandler, "show_error_dialog", lambda self, *a: shown.append(a))
    handler.handle_error(ValueError("x"), "msg", show_dialog=False)
    assert shown == []
    handler.handle_error(eh.DataError(ErrorCode.FILE_CORRUPT, "bad"), "msg")
    assert shown == [("FILE-003", "msg", "bad")]


def test_global_handler_is_shared():
    assert eh.get_error_handler() is eh.get_error_handler()


@pytest.mark.parametrize(
    "cls",
    [
        eh.ValidationError,
        eh.VISAError,
        eh.FileError,
        eh.UIError,
        eh.DataloggerError,
        eh.ToolError,
        eh.ProjectError,
        eh.InstrumentError,
        eh.ConfigError,
        eh.LibraryError,
        eh.SCPIError,
        eh.DataError,
        eh.SystemError,
    ],
)
def test_custom_exceptions_carry_code_and_message(cls):
    exc = cls(ErrorCode.SYS_UNEXPECTED_ERROR, "detail")
    assert exc.error_code is ErrorCode.SYS_UNEXPECTED_ERROR and exc.message == "detail"
    assert str(exc).startswith("[SYS-007]")


# ---------------------------------------------------------------- the reference document


def _documented():
    with open(DOC, encoding="utf-8") as f:
        return re.findall(r"^###\s+([A-Z]+-\d{3})\b", f.read(), re.M)


def test_error_codes_are_unique():
    values = [c.value for c in ErrorCode]
    assert len(values) == len(set(values))
    for value in values:
        assert re.fullmatch(r"\[[A-Z]{2,5}-\d{3}\]", value), value
    documented = _documented()
    assert len(documented) == len(set(documented)), "a code is documented twice"


def test_every_error_code_is_documented():
    documented = set(_documented())
    enum_codes = {c.value.strip("[]") for c in ErrorCode}
    assert sorted(enum_codes - documented) == []


def test_codes_used_in_the_source_are_documented():
    """Every [XXX-nnn] code written in the application, the engine or the native module must
    have its section in ERROR_CODES.md."""
    documented = set(_documented())
    prefixes = {c.split("-")[0] for c in documented}
    sources = (
        glob.glob(os.path.join(REPO, "frontend", "**", "*.py"), recursive=True)
        + glob.glob(os.path.join(REPO, "ola", "**", "*.py"), recursive=True)
        + glob.glob(os.path.join(REPO, "native", "src", "*.rs"))
    )
    missing = {}
    for path in sources:
        with open(path, encoding="utf-8") as f:
            for code in CODE.findall(f.read()):
                if code.split("-")[0] in prefixes and code not in documented:
                    missing.setdefault(code, os.path.relpath(path, REPO))
    assert missing == {}


def test_call_error_classes_have_documented_codes():
    import ola.call_errors as ce

    documented = set(_documented())
    for obj in vars(ce).values():
        if isinstance(obj, type) and issubclass(obj, CallError):
            assert obj.code in documented, obj.__name__


def test_a_code_written_in_the_text_is_kept_when_nothing_else_gives_one(monkeypatch):
    shown = []
    monkeypatch.setattr(
        eh.QMessageBox, "warning",
        staticmethod(lambda parent, title, text: shown.append(text)),
    )
    eh.show_problem(None, "T", "no answer [CALL-004] from the bench")
    assert shown == ["no answer [CALL-004] from the bench"]  # not SYS-007 on top
