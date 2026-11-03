"""Translator, translation files and the structured logger of frontend.core."""

import glob
import json
import logging
import os
import re

import pytest

from frontend.core.logger import Logger
from frontend.core.Translator import Translator
from tests.conftest import REPO

LANG_DIR = os.path.join(REPO, "frontend", "lang")
LOCALES = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(LANG_DIR, "*.json")))
# translator.t('key') / translator.get('key', ...) with a literal key
_USED_KEY = re.compile(r"""\.(?:t|get)\(\s*['"]([A-Za-z0-9_.\-]+)['"]\s*[,)]""")
_TRANSLATOR_CALL = re.compile(r"""translat\w*\.(?:t|get)\(|\btr\.(?:t|get)\(|self\.t\(""")


# ---------------------------------------------------------------- Translator


def test_every_locale_is_available():
    tr = Translator()
    assert set(LOCALES) <= set(tr.available_langs)
    assert {"en", "it"} <= set(LOCALES)


@pytest.mark.parametrize("lang", LOCALES)
def test_switching_language_loads_its_file(lang):
    tr = Translator()
    tr.set_language(lang)
    with open(os.path.join(LANG_DIR, f"{lang}.json"), encoding="utf-8") as f:
        expected = json.load(f)
    assert tr.current_lang == lang and tr.translations == expected
    key = next(iter(expected))
    assert tr.t(key) == expected[key]


def test_missing_key_and_language_fall_back(tmp_path):
    (tmp_path / "en.json").write_text(json.dumps({"hello": "Hello"}), encoding="utf-8")
    tr = Translator(lang_dir=str(tmp_path))
    assert tr.t("hello") == "Hello"
    assert tr.t("unknown_key") == "unknown_key"
    assert tr.get("unknown_key", "Default") == "Default"
    assert tr.get("unknown_key") == "unknown_key"
    tr.set_language("xx")  # no file: no translations, keys are shown
    assert tr.current_lang == "xx" and tr.t("hello") == "hello"


def test_translator_creates_a_missing_directory(tmp_path):
    lang_dir = tmp_path / "lang"
    tr = Translator(lang_dir=str(lang_dir))
    assert lang_dir.is_dir() and tr.available_langs == []


def _used_keys():
    used = {}
    for path in glob.glob(os.path.join(REPO, "frontend", "**", "*.py"), recursive=True):
        with open(path, encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                if not _TRANSLATOR_CALL.search(line):
                    continue
                for key in _USED_KEY.findall(line):
                    used.setdefault(key, f"{os.path.relpath(path, REPO)}:{lineno}")
    return used


def test_keys_used_by_the_code_exist_in_every_locale():
    """A key used with translator.t('...') but missing from a locale shows the raw key in the
    UI. scripts/check_translations.py checks the locales against each other; this checks the
    code against the locales."""
    used = _used_keys()
    assert len(used) > 50
    missing = []
    for lang in LOCALES:
        with open(os.path.join(LANG_DIR, f"{lang}.json"), encoding="utf-8") as f:
            keys = set(json.load(f))
        missing += [f"{lang}: '{k}' ({where})" for k, where in used.items() if k not in keys]
    assert missing == []


# ---------------------------------------------------------------- Logger


@pytest.fixture
def logger():
    log = Logger()
    yield log
    log.set_project_directory(None)


def test_logger_is_a_singleton(logger):
    assert Logger() is logger


def test_project_log_file_has_the_structured_format(logger, tmp_path):
    logger.set_project_directory(str(tmp_path))
    path = logger.get_current_log_file()
    assert path and os.path.dirname(path) == str(tmp_path / "logs")
    logger.info("plain message")
    logger.error("connection lost", error_code="VISA-001")
    logger.warning("[CALL-002] value not handled")
    logger.debug("debug goes to the file")
    logger.file_handler.flush()
    with open(path, encoding="utf-8") as f:
        text = f.read()
    assert re.search(r"^\[\d\d:\d\d:\d\d\] INFO--plain message$", text, re.M)
    assert "ERROR-VISA-001-connection lost" in text
    assert "WARNING-CALL-002-value not handled" in text
    assert "DEBUG--debug goes to the file" in text


def test_changing_project_moves_the_log_file(logger, tmp_path):
    first, second = tmp_path / "p1", tmp_path / "p2"
    logger.set_project_directory(str(first))
    logger.set_project_directory(str(second))
    file_handlers = [
        h for h in logging.getLogger("LabAutomation").handlers if isinstance(h, logging.FileHandler)
    ]
    assert len(file_handlers) == 1
    assert logger.get_current_log_file().startswith(str(second))
    logger.set_project_directory(None)
    assert logger.file_handler is None
