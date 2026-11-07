# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""scripts/add_copyright_headers.py: adds and checks the copyright header of source files.

The script rewrites many files of the repository at once, so these tests check on temporary
files that it puts the header in the right place, keeps the line endings and the BOM, never adds
it twice and never touches files of other kinds.
"""

import importlib.util
import os

import pytest

from tests.conftest import REPO

_SPEC = importlib.util.spec_from_file_location(
    "add_copyright_headers", os.path.join(REPO, "scripts", "add_copyright_headers.py")
)
headers = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(headers)

LINES = [
    "Copyright (C) 2025-2026 Erik Medeossi",
    "This file is part of Open Lab Automation.",
    "Licensed under the GNU General Public License v3.0; see the LICENSE file.",
]


def write(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return path


def run(*paths, check=False):
    return headers.main((["--check"] if check else []) + [str(p) for p in paths])


def read(path):
    return path.read_bytes().decode("utf-8")


def test_header_text_is_the_agreed_one():
    assert headers.LINES == LINES


@pytest.mark.parametrize(
    "ext,expected_first",
    [
        (".py", "# " + LINES[0]),
        (".sh", "# " + LINES[0]),
        (".rs", "// " + LINES[0]),
        (".c", "// " + LINES[0]),
        (".h", "// " + LINES[0]),
        (".bat", "REM " + LINES[0]),
        (".qss", "/*"),
    ],
)
def test_comment_style_of_every_language(tmp_path, ext, expected_first):
    path = write(tmp_path, f"f{ext}", "code\n")
    assert run(path) == 0
    text = read(path)
    assert text.splitlines()[0] == expected_first
    assert all(line in text for line in LINES)
    assert text.endswith("code\n")


def test_qss_header_is_a_closed_block_comment(tmp_path):
    path = write(tmp_path, "style.qss", "QWidget { color: red; }\n")
    run(path)
    assert read(path).startswith("/*\n * " + LINES[0] + "\n")
    assert "\n */\n" in read(path)


def test_python_header_goes_after_shebang_and_coding_line(tmp_path):
    path = write(
        tmp_path, "tool.py", "#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\nimport os\n"
    )
    run(path)
    lines = read(path).splitlines()
    assert lines[0] == "#!/usr/bin/env python3"
    assert lines[1] == "# -*- coding: utf-8 -*-"
    assert lines[2] == "# " + LINES[0]
    assert lines[-1] == "import os"


def test_shell_script_keeps_its_shebang_first(tmp_path):
    path = write(tmp_path, "run.sh", "#!/bin/bash\nset -e\n")
    run(path)
    lines = read(path).splitlines()
    assert lines[0] == "#!/bin/bash" and lines[1] == "# " + LINES[0] and lines[-1] == "set -e"


def test_batch_file_keeps_echo_off_first(tmp_path):
    path = write(tmp_path, "build.bat", "@echo off\r\ngcc a.c\r\n")
    run(path)
    lines = read(path).splitlines()
    assert lines[0] == "@echo off" and lines[1] == "REM " + LINES[0]


def test_crlf_files_stay_crlf(tmp_path):
    path = write(tmp_path, "win.py", "import os\r\nprint(os.name)\r\n")
    run(path)
    raw = path.read_bytes()
    assert raw.count(b"\r\n") == raw.count(b"\n")  # no bare LF was introduced
    assert raw.startswith(b"# Copyright (C) 2025-2026 Erik Medeossi\r\n")


def test_lf_files_stay_lf(tmp_path):
    path = write(tmp_path, "unix.py", "import os\n")
    run(path)
    assert b"\r" not in path.read_bytes()


def test_utf8_bom_is_kept_in_front(tmp_path):
    path = write(tmp_path, "bom.py", b"\xef\xbb\xbfimport os\n")
    run(path)
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf# Copyright")
    assert raw.count(b"\xef\xbb\xbf") == 1


def test_non_ascii_content_is_preserved(tmp_path):
    path = write(tmp_path, "unicode.py", 'name = "Temperatura °C – è"\n')
    run(path)
    assert read(path).endswith('name = "Temperatura °C – è"\n')


def test_empty_file_gets_only_the_header(tmp_path):
    path = write(tmp_path, "empty.py", "")
    run(path)
    assert read(path).splitlines() == ["# " + line for line in LINES]


def test_file_without_final_newline(tmp_path):
    path = write(tmp_path, "tail.py", "x = 1")
    run(path)
    assert read(path).endswith("x = 1")
    assert "x = 1" in read(path).splitlines()[-1]


def test_header_is_not_added_twice(tmp_path):
    path = write(tmp_path, "twice.py", "import os\n")
    run(path)
    first = path.read_bytes()
    assert run(path) == 0
    assert path.read_bytes() == first
    assert read(path).count(LINES[0]) == 1


def test_existing_header_after_shebang_is_recognised(tmp_path):
    original = "#!/usr/bin/env python3\n# " + LINES[0] + "\nimport os\n"
    path = write(tmp_path, "has.py", original)
    run(path)
    assert read(path) == original


def test_other_file_kinds_are_not_touched(tmp_path, capsys):
    for name in ("README.md", "data.json", "lang.yml", "notes.txt"):
        write(tmp_path, name, "content\n")
    paths = [tmp_path / n for n in ("README.md", "data.json", "lang.yml", "notes.txt")]
    assert run(*paths) == 0
    assert "0 file(s) changed" in capsys.readouterr().out
    assert all(read(p) == "content\n" for p in paths)


def test_check_lists_missing_files_and_exits_1(tmp_path, capsys):
    good = write(tmp_path, "good.py", "# " + LINES[0] + "\nx = 1\n")
    bad = write(tmp_path, "bad.py", "x = 1\n")
    assert run(good, bad, check=True) == 1
    out = capsys.readouterr().out
    listed = [ln for ln in out.splitlines() if ln.startswith("missing copyright header: ")]
    assert len(listed) == 1 and listed[0].endswith("bad.py")  # paths are relative to the repo
    assert "good.py" not in out
    assert "1 of 2 files have the header" in out
    assert read(bad) == "x = 1\n"  # --check never writes


def test_check_passes_when_every_file_has_it(tmp_path, capsys):
    path = write(tmp_path, "ok.py", "x = 1\n")
    run(path)
    assert run(path, check=True) == 0
    assert "1 of 1 files have the header" in capsys.readouterr().out


def test_report_lists_the_changed_files(tmp_path, capsys):
    changed = write(tmp_path, "new.py", "x = 1\n")
    write(tmp_path, "old.py", "# " + LINES[0] + "\n")
    run(changed, tmp_path / "old.py")
    out = capsys.readouterr().out
    assert "added: " in out and "new.py" in out
    assert "1 file(s) changed, 1 already had it" in out


def test_tracked_files_selection_uses_git(tmp_path, monkeypatch):
    """Without file arguments the script works on the git-tracked files of the repository
    that have a known extension."""
    (tmp_path / "a.py").write_text("x\n")
    (tmp_path / "b.md").write_text("x\n")
    monkeypatch.setattr(headers, "ROOT", str(tmp_path))

    class Done:
        stdout = "a.py\nb.md\nmissing.py\n"

    monkeypatch.setattr(headers.subprocess, "run", lambda *a, **k: Done())
    assert headers.tracked_files() == [str(tmp_path / "a.py")]
