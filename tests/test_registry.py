"""Module discovery and loading."""

import json
from pathlib import Path

import pytest

from ola.measurement import Measurement
from ola.registry import (
    BUILTIN_DIR,
    ModuleLoadError,
    ModuleNotTrustedError,
    ModuleRegistry,
    default_registry,
)


def make_module(root: Path, folder: str, manifest=None, code=None, **overrides):
    d = root / folder
    d.mkdir(parents=True)
    base = {
        "id": folder,
        "name": folder.title(),
        "version": "1.0.0",
        "api_version": 1,
        "extension": f".{folder[:4]}",
        "entry": "measurement.py:M",
        "roles": [],
    }
    base.update(overrides)
    (d / "module.json").write_text(json.dumps(manifest if manifest is not None else base))
    if code is not None:
        (d / "measurement.py").write_text(code)
    return d


GOOD = (
    "from ola.measurement import Measurement\nclass M(Measurement):\n    def run(self, ctx): pass\n"
)


def test_builtin_time_log_is_found():
    reg = default_registry(user_dir=Path("/nonexistent"))
    assert [m.id for m in reg.list()] == ["time_log"]
    info = reg.get("time_log")
    assert info.builtin and info.extension == ".tlg" and reg.by_extension(".TLG") is info
    assert reg.problems == []
    assert info.roles[0].name == "instruments" and info.roles[0].multiple


def test_builtin_dir_is_inside_the_package():
    assert BUILTIN_DIR.is_dir() and (BUILTIN_DIR / "time_log" / "module.json").is_file()


@pytest.mark.parametrize(
    "override,message",
    [
        ({"id": "Bad-Id"}, "invalid id"),
        ({"api_version": 99}, "api_version 99"),
        ({"extension": "eff"}, "invalid extension"),
        ({"extension": ".json"}, "reserved"),
        ({"extension": ".was"}, "reserved"),
        ({"entry": "measurement"}, "invalid entry"),
        ({"entry": "../x.py:M"}, "invalid entry"),
        ({"roles": [{"name": "a"}]}, "'name' and 'category'"),
        (
            {"roles": [{"name": "a", "category": "x"}, {"name": "a", "category": "x"}]},
            "duplicate role",
        ),
        ({"roles": [{"name": "a", "category": "x", "typo": 1}]}, "unknown field"),
        ({"params_schema": []}, "params_schema"),
        ({"version": 1}, "'version' must be str"),
    ],
)
def test_invalid_manifests_are_reported_not_fatal(tmp_path, override, message):
    make_module(tmp_path, "good", code=GOOD, extension=".good")
    make_module(tmp_path, "bad", **override)
    reg = ModuleRegistry([(tmp_path, False)])
    reg.discover()
    assert [m.id for m in reg.list()] == ["good"]
    assert len(reg.problems) == 1 and message in reg.problems[0][1]
    assert reg.problems[0][0].name == "bad"


def test_unreadable_manifest(tmp_path):
    d = tmp_path / "broken"
    d.mkdir()
    (d / "module.json").write_text("{not json")
    reg = ModuleRegistry([(tmp_path, False)])
    reg.discover()
    assert reg.list() == [] and "cannot read module.json" in reg.problems[0][1]


def test_duplicate_id_and_extension_first_wins(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    make_module(a, "alpha", extension=".aaa")
    make_module(b, "alpha", extension=".bbb")  # same id, other folder
    make_module(b, "beta", extension=".aaa")  # same extension as alpha
    reg = ModuleRegistry([(a, True), (b, False)])
    reg.discover()
    assert [m.id for m in reg.list()] == ["alpha"] and reg.get("alpha").builtin
    messages = sorted(m for _, m in reg.problems)
    assert any("duplicate module id" in m for m in messages)
    assert any("already used by 'alpha'" in m for m in messages)


def test_discovery_never_runs_module_code(tmp_path):
    marker = tmp_path / "executed"
    make_module(tmp_path, "evil", code=f"open({str(marker)!r}, 'w').write('x')\n")
    reg = ModuleRegistry([(tmp_path, False)])
    reg.discover()
    assert [m.id for m in reg.list()] == ["evil"] and not marker.exists()


def test_user_code_needs_explicit_permission(tmp_path):
    marker = tmp_path / "executed"
    make_module(tmp_path, "evil", code=f"open({str(marker)!r}, 'w').write('x')\n" + GOOD)
    reg = ModuleRegistry([(tmp_path, False)])
    reg.discover()
    with pytest.raises(ModuleNotTrustedError):
        reg.create("evil", {})
    assert not marker.exists()
    reg.create("evil", {}, allow_user_code=True)  # the user said yes
    assert marker.exists()


def test_create_sets_info_and_roles(tmp_path):
    make_module(tmp_path, "mine", code=GOOD, roles=[{"name": "psu", "category": "power_supply"}])
    reg = ModuleRegistry([(tmp_path, False)])
    reg.discover()
    m = reg.create("mine", {"x": 1}, allow_user_code=True)
    assert isinstance(m, Measurement) and m.params == {"x": 1}
    assert m.info.id == "mine" and m.roles[0].name == "psu"


def test_load_errors_are_wrapped(tmp_path):
    make_module(tmp_path, "syntax", code="def broken(:\n")
    make_module(tmp_path, "noclass", code="x = 1\n")
    make_module(tmp_path, "wrongtype", code="class M:\n    pass\n")
    reg = ModuleRegistry([(tmp_path, False)])
    reg.discover()
    for module_id in ("syntax", "noclass", "wrongtype"):
        with pytest.raises(ModuleLoadError):
            reg.create(module_id, {}, allow_user_code=True)
    # one broken module does not affect the others
    make_module(tmp_path / "other", "fine", code=GOOD)


def test_unknown_module_id(tmp_path):
    reg = ModuleRegistry([(tmp_path, False)])
    reg.discover()
    from ola.measurement import MeasurementError

    with pytest.raises(MeasurementError, match="unknown measurement type"):
        reg.get("nope")
    assert reg.by_extension(".zzz") is None


def test_missing_search_dirs_are_ignored(tmp_path):
    reg = ModuleRegistry([(tmp_path / "does-not-exist", False)])
    assert reg.discover() == []
