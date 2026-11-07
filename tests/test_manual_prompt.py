"""The pop-up for manual instruments (no screen needed, see conftest.py)."""

import threading
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

from frontend.ui.manual_prompt import ManualPrompter  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def ask_in_thread(prompter, request, cancel=None):
    """Call the prompter the way a run does (from another thread); returns (thread, result)."""
    result = {}

    def work():
        result["value"] = prompter(request, cancel)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    return thread, result


def pump(app, condition, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


REQUEST = SimpleNamespace(text="Set 'VIN' to 12 V")


def test_done_returns_true(app):
    prompter = ManualPrompter()
    thread, result = ask_in_thread(prompter, REQUEST)
    assert pump(app, lambda: prompter.dialogs)
    labels = [lab.text() for lab in prompter.dialogs[0].findChildren(QLabel)]
    assert "Set 'VIN' to 12 V" in labels
    prompter.dialogs[0].done_button.click()
    thread.join(5)
    assert result["value"] is True and not prompter.dialogs


def test_cancel_returns_false(app):
    prompter = ManualPrompter()
    thread, result = ask_in_thread(prompter, REQUEST)
    assert pump(app, lambda: prompter.dialogs)
    prompter.dialogs[0].cancel_button.click()
    thread.join(5)
    assert result["value"] is False


def test_stopping_the_run_closes_the_popup_and_cancels(app):
    prompter = ManualPrompter()
    stop = threading.Event()
    thread, result = ask_in_thread(prompter, REQUEST, stop)
    assert pump(app, lambda: prompter.dialogs)
    stop.set()
    assert pump(app, lambda: not prompter.dialogs)
    thread.join(5)
    assert result["value"] is False


def test_calling_it_from_the_gui_thread_is_refused(app):
    with pytest.raises(RuntimeError, match="thread of a run"):
        ManualPrompter()(REQUEST)
