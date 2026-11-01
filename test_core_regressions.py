# Regression tests for bugs fixed in core / backend layers.

import os
import socket
import subprocess
import threading

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- Translator
def test_translator_get_with_default():
    from frontend.core.Translator import Translator

    tr = Translator(default_lang="en")
    assert tr.get("settings") == tr.t("settings")
    assert tr.get("__missing_key__", "fallback") == "fallback"
    assert tr.get("__missing_key__") == "__missing_key__"


def test_translations_complete():
    result = subprocess.run(
        ["python", os.path.join(ROOT, "scripts", "check_translations.py")],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# ----------------------------------------------------------------- validator
@pytest.mark.parametrize("address", [
    "TCPIP0::192.168.1.5::inst0::INSTR",
    "TCPIP0::192.168.1.5::hislip0::INSTR",
    "TCPIP0::192.168.1.5::5025::SOCKET",
    "USB0::0x1AB1::0x04CE::DS1ZA123::INSTR",
    "GPIB0::5::INSTR",
    "ASRL3::INSTR",
])
def test_visa_addresses_generated_by_app_are_valid(address):
    from frontend.core.validator import is_valid_visa_address

    assert is_valid_visa_address(address)


def test_visa_invalid_address_rejected():
    from frontend.core.errorhandler import ValidationError
    from frontend.core.validator import is_valid_visa_address

    with pytest.raises(ValidationError):
        is_valid_visa_address("not-a-visa-address")


# --------------------------------------------------------------------- tools
def test_save_json_relative_path_without_directory(tmp_path, monkeypatch):
    from frontend.core.tools import read_json, save_json, save_csv

    monkeypatch.chdir(tmp_path)
    save_json({"a": 1}, "out.json")
    assert read_json("out.json") == {"a": 1}
    save_csv([["1", "2"]], "out.csv", headers=["x", "y"])
    assert os.path.exists("out.csv")


# ------------------------------------------------- ProjectDatabaseManager
def test_project_db_manager_module_is_sane():
    import frontend.core.ProjectDatabaseManager as mod

    assert mod.__doc__.count("Ogni progetto ha il proprio database.") == 1
    mgr = mod.ProjectDatabaseManager(project_name="Test DC-DC Converter")
    assert mgr.db_name == "test_dc_dc_converter"

    class _FakeConn:
        closed = False

        def cursor(self):
            return self

        def close(self):
            pass

    # empty data must return 0 rows instead of raising NameError
    mgr.connect_project_db = lambda: _FakeConn()
    assert mgr.insert_measurement_data("t", {}, []) == 0


# ----------------------------------------------------------------- C backend
@pytest.fixture(scope="module")
def backend():
    from frontend.core.c_backend import CBackend

    try:
        CBackend.load()
    except FileNotFoundError:
        pytest.skip("C backend not built (run backend/build.sh)")
    yield CBackend
    CBackend.unload()


@pytest.fixture()
def fake_instrument():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(64)

    def handle(conn):
        volt = 0.0
        f = conn.makefile("rwb")
        for line in f:
            text = line.decode().strip()
            if text.startswith("VOLT "):
                volt = float(text.split()[1])
            elif text == "MEAS:VOLT?":
                f.write(f"{volt:+.6E}\n".encode())
                f.flush()
            elif text == "MEAS:CURR?":
                f.write(f"{volt / 10:+.6E}\n".encode())
                f.flush()
            elif text == "*IDN?":
                f.write(b"FAKE,1\n")
                f.flush()

    def serve():
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                return
            threading.Thread(target=handle, args=(conn,), daemon=True).start()

    threading.Thread(target=serve, daemon=True).start()
    yield srv.getsockname()[1]
    srv.close()


def test_backend_pool_slots_are_reused(backend, fake_instrument):
    # more than BE_MAX_INSTRUMENTS (32) connect/disconnect cycles must work
    for _ in range(100):
        handle = backend.connect("127.0.0.1", fake_instrument)
        backend.disconnect(handle)


def test_backend_query_and_sweep(backend, fake_instrument):
    handle = backend.connect("127.0.0.1", fake_instrument)
    try:
        assert backend.query(handle, "*IDN?") == "FAKE,1"
        volts, amps = backend.sweep_run([handle], [1], [1.0, 2.0, 3.0], 0.0)
        assert volts == [1.0, 2.0, 3.0]
        assert amps == pytest.approx([0.1, 0.2, 0.3])
    finally:
        backend.disconnect(handle)
