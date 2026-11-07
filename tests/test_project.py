"""Project with several measurements, one file per measurement."""

import json

import pytest

from ola.measurement import MeasurementError
from ola.project import MeasurementFile, Project, check_plain_filename
from ola.registry import default_registry


@pytest.fixture
def registry(tmp_path):
    return default_registry(user_dir=tmp_path / "no-user-modules")


def test_new_project_add_save_load_roundtrip(tmp_path, registry):
    p = Project.new("Pippo", tmp_path / "pippo", inst_file="pippo.inst")
    r1 = p.add_measurement("time_log", "Temperature log", registry, {"interval_s": 2})
    r2 = p.add_measurement("time_log", "Temperature log", registry)
    assert (r1.id, r2.id) == ("m1", "m2")
    assert r1.file == "temperature_log.tlg" and r2.file == "temperature_log_2.tlg"
    p.extra["project_id"] = "keep-me"
    p.save()

    loaded = Project.load(p.path)
    assert loaded.name == "Pippo" and loaded.inst_file == "pippo.inst"
    assert [vars(m) for m in loaded.measurements] == [vars(r1), vars(r2)]
    assert loaded.extra == {"project_id": "keep-me"}
    assert loaded.validate(registry) == []

    mf = MeasurementFile.load(loaded.file_path(r1))
    assert (mf.type, mf.module_version, mf.params) == ("time_log", "1.0.0", {"interval_s": 2})


def test_measurement_file_roundtrip_and_errors(tmp_path):
    path = tmp_path / "x.tlg"
    MeasurementFile(
        "time_log", "1.0.0", role_bindings={"instruments": ["dmm1", "psu1"]}, params={"a": 1}
    ).save(path)
    mf = MeasurementFile.load(path)
    assert mf.role_bindings == {"instruments": ["dmm1", "psu1"]} and mf.api_version == 1
    path.write_text("{broken")
    with pytest.raises(MeasurementError, match="cannot read"):
        MeasurementFile.load(path)
    path.write_text(json.dumps({"params": {}}))
    with pytest.raises(MeasurementError, match="missing 'type'"):
        MeasurementFile.load(path)


def test_old_project_format_is_not_read(tmp_path):
    old = tmp_path / "old.json"
    old.write_text(
        json.dumps({"project_name": "Old", "eff_files": ["eff.eff"], "was_files": ["osc1.was"]})
    )
    with pytest.raises(MeasurementError, match="not supported"):
        Project.load(old)


def test_load_errors(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2]")
    with pytest.raises(MeasurementError, match="not a project file"):
        Project.load(bad)
    bad.write_text(json.dumps({"format_version": 2, "measurements": [{"id": "m1"}]}))
    with pytest.raises(MeasurementError, match="invalid measurement entry"):
        Project.load(bad)
    with pytest.raises(MeasurementError, match="cannot read"):
        Project.load(tmp_path / "missing.json")


def test_add_does_not_overwrite_existing_files(tmp_path, registry):
    p = Project.new("P", tmp_path)
    (tmp_path / "log.tlg").write_text("precious")
    ref = p.add_measurement("time_log", "log", registry)
    assert ref.file == "log_2.tlg" and (tmp_path / "log.tlg").read_text() == "precious"


def test_remove_measurement(tmp_path, registry):
    p = Project.new("P", tmp_path)
    ref = p.add_measurement("time_log", "a", registry)
    path = p.file_path(ref)
    p.remove_measurement(ref.id)  # file stays unless asked
    assert path.exists() and p.measurements == []
    ref = p.add_measurement("time_log", "b", registry)
    p.remove_measurement(ref.id, delete_file=True)
    assert not (tmp_path / ref.file).exists()
    with pytest.raises(MeasurementError):
        p.get("m99")


def test_validate_reports_problems(tmp_path, registry):
    from ola.project import MeasurementRef

    p = Project.new("P", tmp_path)
    p.add_measurement("time_log", "ok", registry)
    p.measurements += [
        MeasurementRef("m1", "time_log", "dup id", "other.tlg"),  # duplicate id, file missing
        MeasurementRef("m5", "spectrumx", "no module", "e.spx"),  # unknown type
        MeasurementRef("m6", "time_log", "wrong ext", "x.json"),  # wrong extension
        MeasurementRef("m7", "time_log", "evil", "../outside.tlg"),  # path traversal
        MeasurementRef("m8", "time_log", "same file", "OK.tlg"),  # same file as the first
    ]
    text = "\n".join(p.validate(registry))
    for expected in (
        "duplicate measurement id 'm1'",
        "unknown measurement type 'spectrumx'",
        "should end with .tlg",
        "invalid file name '../outside.tlg'",
        "also used by m1",
        "'other.tlg' is missing",
    ):
        assert expected in text, (expected, text)


@pytest.mark.parametrize("name", ["../x.tlg", "a/b.tlg", "a\\b.tlg", "..", ".", "C:evil.tlg", ""])
def test_unsafe_file_names_are_rejected(name):
    with pytest.raises(MeasurementError):
        check_plain_filename(name)


def test_file_path_refuses_traversal(tmp_path):
    from ola.project import MeasurementRef

    p = Project.new("P", tmp_path)
    with pytest.raises(MeasurementError):
        p.file_path(MeasurementRef("m1", "time_log", "x", "../../etc/passwd"))
