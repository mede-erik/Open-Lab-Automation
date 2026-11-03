"""The command-line tools in scripts/, run as a user runs them (subprocess, no hardware)."""

import json
import os
import shutil
import subprocess
import sys

import pytest

from ola import tester
from tests.conftest import REPO, needs_library

SCRIPTS = os.path.join(REPO, "scripts")


def run(script, *args, stdin=None, env=None, timeout=60):
    return subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, script), *args],
        input=stdin,
        capture_output=True,
        text=True,
        cwd=REPO,
        env={**os.environ, **(env or {})},
        timeout=timeout,
    )


# ---------------------------------------------------------------- check_translations.py


def test_translations_of_the_repository_are_consistent():
    result = run("check_translations.py")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 problem(s)" in result.stdout


@pytest.fixture
def lang_dir(tmp_path):
    d = tmp_path / "lang"
    d.mkdir()
    (d / "en.json").write_text(
        json.dumps({"hello": "Hello {name}", "bye": "Bye"}), encoding="utf-8"
    )
    return d


def _write(d, name, data):
    (d / name).write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def test_translations_ok(lang_dir):
    _write(lang_dir, "it.json", {"hello": "Ciao {name}", "bye": "Ciao"})
    result = run("check_translations.py", "--lang-dir", str(lang_dir))
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize(
    "content,expected",
    [
        ({"hello": "Ciao {name}"}, "bye"),  # missing key
        ({"hello": "Ciao {name}", "bye": "Ciao", "extra": "x"}, "extra"),  # extra key
        ({"hello": "Ciao {nome}", "bye": "Ciao"}, "name"),  # placeholder changed
        ({"hello": "Ciao {name}", "bye": ""}, "bye"),  # empty text
        ({"hello": "Ciao {name}", "bye": 3}, "bye"),  # not text
        ("{broken", "it"),  # invalid JSON
    ],
)
def test_translation_problems_fail(lang_dir, content, expected):
    _write(lang_dir, "it.json", content)
    result = run("check_translations.py", "--lang-dir", str(lang_dir))
    assert result.returncode == 1
    assert expected in result.stdout + result.stderr


# ---------------------------------------------------------------- dry_run_call.py


@needs_library
def test_dry_run_single_call():
    result = run(
        "dry_run_call.py",
        "--model",
        "OSC_Siglent_SDS824X_HD",
        "--call",
        "set_channel_scale",
        "--arg",
        "channel_number=1",
        "--arg",
        "value=0.5",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "set_channel_scale" in result.stdout and "0.5" in result.stdout


@needs_library
def test_dry_run_translates_the_answer(library):
    model = "OSC_Tek_MSO54"
    query = library.commands(model)["query_trigger_status"]["query"]
    answer, logical = next(iter(query["response_map"].items()))
    result = run(
        "dry_run_call.py", "--model", model, "--call", "query_trigger_status", "--answer", answer
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert repr(logical) in result.stdout


@needs_library
def test_dry_run_was_file():
    was = os.path.join(REPO, "examples", "test-dcdc-project", "osc1.was")
    result = run("dry_run_call.py", "--model", "OSC_Rigol_DS1054Z", "--was", was)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "set_timebase_scale" in result.stdout


@needs_library
@pytest.mark.parametrize(
    "args",
    [
        ["--model", "NOPE", "--call", "reset"],
        ["--model", "OSC_Rigol_DS1054Z", "--call", "no_such_call"],
        ["--model", "OSC_Rigol_DS1054Z", "--call", "set_channel_scale", "--arg", "value=x"],
    ],
)
def test_dry_run_errors_exit_with_1(args):
    result = run("dry_run_call.py", *args)
    assert result.returncode != 0
    assert "Traceback" not in result.stderr


# ---------------------------------------------------------------- instrument_shell.py


def _menu_index(items, wanted):
    return str([key for key, *_ in items].index(wanted) + 1)


@needs_library
def test_instrument_shell_simulated_session(library, tmp_path):
    """A full session with the simulated instrument: choose category, model and interface,
    then use the read-only commands."""
    category = "power_supplies_series"
    model = tester.models_of(library, category)[0][0]
    script = "\n".join(
        [
            _menu_index(tester.categories(library), category),
            _menu_index(tester.models_of(library, category), model),
            "1",  # the only interface with --sim: the simulated instrument
            "missing",
            "calls",
            "plan set_voltage channel_number=1 value=1.5",
            "call identification_query",
            "test",
            "quit",
            "",
        ]
    )
    result = run(
        "instrument_shell.py",
        "--sim",
        stdin=script,
        env={"HOME": str(tmp_path), "USERPROFILE": str(tmp_path)},
    )
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert f"Connected to {model}" in out
    assert "Traceback" not in out
    assert "1.5" in out  # the planned set_voltage command


def test_instrument_shell_missing_library(tmp_path):
    result = run("instrument_shell.py", "--library", str(tmp_path / "missing.json"))
    assert result.returncode != 0 and "library not found" in result.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_backend_build_script_is_valid_bash():
    result = subprocess.run(
        ["bash", "-n", os.path.join(REPO, "backend", "build.sh")], capture_output=True
    )
    assert result.returncode == 0, result.stderr
