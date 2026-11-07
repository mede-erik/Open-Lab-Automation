# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""frontend.core.tools: file helpers and the TCP connection diagnostics (against a local
listening socket, no instrument)."""

import os
import socket
import time
from datetime import datetime

import pytest

from frontend.core import tools


def test_json_round_trip_keeps_unicode(tmp_path):
    path = tmp_path / "sub" / "dir" / "data.json"
    data = {"name": "Temperatura °C", "values": [1, 2.5, None], "nested": {"ok": True}}
    tools.save_json(data, str(path))
    assert tools.read_json(str(path)) == data
    assert "°C" in path.read_text(encoding="utf-8")


def test_read_json_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        tools.read_json(str(tmp_path / "missing.json"))
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        tools.read_json(str(bad))


def test_csv_round_trip(tmp_path):
    path = tmp_path / "out" / "m.csv"
    rows = [["1", "a,b"], ["2", 'quote "x"']]
    tools.save_csv(rows, str(path), headers=["n", "text"])
    headers, data = tools.read_csv(str(path))
    assert headers == ["n", "text"] and data == rows
    assert tools.read_csv(str(path), has_headers=False) == (None, [["n", "text"]] + rows)


def test_csv_without_headers_and_missing_file(tmp_path):
    path = tmp_path / "plain.csv"
    tools.save_csv([["x"]], str(path))
    assert tools.read_csv(str(path), has_headers=False) == (None, [["x"]])
    with pytest.raises(FileNotFoundError):
        tools.read_csv(str(tmp_path / "missing.csv"))


def test_datetime_round_trip():
    dt = datetime(2025, 10, 7, 11, 35, 36)
    text = tools.format_datetime(dt)
    assert text == "2025-10-07 11:35:36"
    assert tools.parse_datetime(text) == dt
    assert tools.format_datetime(dt, "%d/%m/%Y") == "07/10/2025"
    with pytest.raises(ValueError):
        tools.parse_datetime("07/10/2025")


def test_directories_and_sizes(tmp_path):
    target = tmp_path / "a" / "b"
    tools.ensure_directory_exists(str(target))
    tools.ensure_directory_exists(str(target))  # idempotent
    assert target.is_dir()
    f = target / "f.bin"
    f.write_bytes(b"12345")
    assert tools.get_file_size(str(f)) == 5
    with pytest.raises(FileNotFoundError):
        tools.get_file_size(str(target / "nope"))


def test_is_file_newer(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    old.write_text("1")
    new.write_text("2")
    now = time.time()
    os.utime(old, (now - 100, now - 100))
    assert tools.is_file_newer(str(new), str(old))
    assert not tools.is_file_newer(str(old), str(new))
    with pytest.raises(FileNotFoundError):
        tools.is_file_newer(str(new), str(tmp_path / "missing"))


def test_clean_filename():
    assert tools.clean_filename(' a<b>c:d"e/f\\g|h?i*j ') == "a_b_c_d_e_f_g_h_i_j"
    assert tools.clean_filename("ok.csv") == "ok.csv"


def test_generate_unique_filename(tmp_path):
    base = str(tmp_path / "meas")
    first = tools.generate_unique_filename(base, "csv")
    assert first == base + ".csv"
    open(first, "w").close()
    second = tools.generate_unique_filename(base, ".csv")
    assert second == base + "_1.csv"
    open(second, "w").close()
    assert tools.generate_unique_filename(base, "csv") == base + "_2.csv"


# ---------------------------------------------------------------- diagnose_connection


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_diagnose_open_port():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    try:
        port = srv.getsockname()[1]
        result = tools.diagnose_connection(f"TCPIP0::127.0.0.1::{port}::SOCKET")
    finally:
        srv.close()
    assert result["address_valid"] and result["host_resolves"]
    assert result["host"] == "127.0.0.1" and result["port"] == port
    assert result["host_reachable"] and result["port_open"]


def test_diagnose_refused_port():
    port = _free_port()
    result = tools.diagnose_connection(f"TCPIP0::127.0.0.1::{port}::SOCKET")
    assert result["address_valid"] and result["host_reachable"]
    assert not result["port_open"]
    assert any(str(port) in r for r in result["recommendations"])


@pytest.mark.parametrize(
    "address,port",
    [
        ("TCPIP0::127.0.0.1::inst0::INSTR", 111),
        ("TCPIP0::127.0.0.1::INSTR", 111),
        ("TCPIP0::127.0.0.1::hislip0::INSTR", 4880),
        ("TCPIP0::127.0.0.1::hislip0,4999::INSTR", 4999),
    ],
)
def test_diagnose_port_from_address(address, port, monkeypatch):
    calls = []

    def fake_connect(addr, timeout=None):
        calls.append(addr)
        raise ConnectionRefusedError

    monkeypatch.setattr(socket, "create_connection", fake_connect)
    result = tools.diagnose_connection(address)
    assert result["port"] == port and calls == [("127.0.0.1", port)]


def test_diagnose_unrecognised_address():
    result = tools.diagnose_connection("USB0::0x1AB1::0x04CE::X::INSTR")
    assert not result["address_valid"] and not result["port_open"]
    assert any("not recognized" in r for r in result["recommendations"])


def test_diagnose_unresolvable_host(monkeypatch):
    def fail(*_a, **_k):
        raise socket.gaierror("no such host")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    result = tools.diagnose_connection("TCPIP0::no-such-host.invalid::inst0::INSTR")
    assert result["address_valid"] and not result["host_resolves"]
    assert not result["host_reachable"]
