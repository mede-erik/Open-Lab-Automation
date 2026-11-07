# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""frontend.core.ProjectDatabaseManager (PostgreSQL storage of the measurements).

The name sanitising and the error codes are always tested. The full life cycle (database,
numbered tables, insert, query, delete) runs against a real server when the environment
variable OLA_TEST_POSTGRES gives one, e.g.

    OLA_TEST_POSTGRES="host=127.0.0.1 port=5432 user=postgres password=postgres" pytest

The CI job ``postgres`` sets it with a PostgreSQL service container.
"""

import os
import socket
import uuid
from datetime import datetime

import pytest

from frontend.core.ProjectDatabaseManager import ProjectDatabaseManager

DSN = os.environ.get("OLA_TEST_POSTGRES", "")


def _dsn_params():
    params = dict(item.split("=", 1) for item in DSN.split())
    return {
        "host": params.get("host", "127.0.0.1"),
        "port": int(params.get("port", 5432)),
        "user": params.get("user", "postgres"),
        "password": params.get("password", ""),
    }


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Test DC-DC Converter", "test_dc_dc_converter"),
        ("  Prova  #1  ", "prova_1"),
        ("2025 buck", "proj_2025_buck"),
        ("Ünïcode", "n_code"),
        ("___", "unnamed_project"),
    ],
)
def test_database_name_is_sanitised(name, expected):
    assert ProjectDatabaseManager(project_name=name).db_name == expected


@pytest.mark.parametrize(
    "name,expected",
    [
        ("eff.eff", "eff"),
        ("Efficiency Vin=12V.eff", "efficiency_vin_12v"),
        ("1st run.eff", "eff_1st_run"),
        (".eff", "unnamed_eff"),
    ],
)
def test_table_name_is_sanitised(name, expected):
    assert ProjectDatabaseManager()._sanitize_table_name(name) == expected


def test_sanitised_names_cannot_inject_sql():
    db = ProjectDatabaseManager(project_name='x"; DROP DATABASE postgres; --')
    assert db.db_name.replace("_", "").isalnum()


def test_without_project_name():
    db = ProjectDatabaseManager()
    assert db.db_name is None
    for action in (db.connect_project_db, db.create_project_database, db.delete_project_database):
        with pytest.raises(Exception, match=r"\[PJDB-002\]"):
            action()


def test_unreachable_server_reports_pjdb_001():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    db = ProjectDatabaseManager(host="127.0.0.1", port=port, project_name="p")
    with pytest.raises(Exception, match=r"\[PJDB-001\]"):
        db.connect_postgres()
    with pytest.raises(Exception, match=r"\[PJDB-003\]"):
        db.list_project_tables()


# ---------------------------------------------------------------- real server


@pytest.fixture
def db():
    if not DSN:
        pytest.skip("set OLA_TEST_POSTGRES to run against a PostgreSQL server")
    manager = ProjectDatabaseManager(
        **_dsn_params(), project_name=f"ola test {uuid.uuid4().hex[:8]}"
    )
    assert manager.create_project_database() is True
    assert manager.create_project_database() is True  # already exists: no error
    yield manager
    manager.delete_project_database()


def test_efficiency_tables_are_numbered(db):
    first = db.create_efficiency_table(
        "Eff Run.eff", {"operator": "VARCHAR(100)", "notes": "TEXT"}, ["vin"], ["eff"]
    )
    second = db.create_efficiency_table("Eff Run.eff", {}, ["vin"], ["eff"])
    assert (first, second) == ("eff_run_1", "eff_run_2")
    assert db.get_next_table_number("Eff Run.eff") == 3
    assert {"eff_run_1", "eff_run_2"} <= set(db.list_project_tables())


def test_insert_and_read_back(db):
    table = db.create_efficiency_table(
        "eff.eff",
        {"operator": "VARCHAR(100)", "started": "TIMESTAMP"},
        ["vin", "iout"],
        ["efficiency", "temperature"],
    )
    info = {"operator": "Lab", "started": datetime(2025, 10, 7, 10, 0, 0)}
    rows = [
        {"vin": 12.0, "iout": 1.0, "efficiency": 91.5, "temperature": 30.0},
        {"vin": 12.0, "iout": 2.0, "efficiency": 93.0, "temperature": 35.5},
        {"vin": 24.0, "iout": 1.0, "efficiency": 90.1, "temperature": 31.0},
    ]
    assert db.insert_measurement_data(table, info, rows) == 3
    assert db.insert_measurement_data(table, info, []) == 0
    every = db.get_table_data(table)
    assert len(every) == 3 and every[0]["operator"] == "Lab"
    assert every[0]["started"] == info["started"] and every[0]["created_at"] is not None
    at_12v = db.get_table_data(table, conditions={"vin": 12.0})
    assert sorted(r["iout"] for r in at_12v) == [1.0, 2.0]
    assert len(db.get_table_data(table, limit=1)) == 1


def test_invalid_column_type_is_refused(db):
    with pytest.raises(Exception, match=r"\[PJDB-006\]"):
        db.create_efficiency_table("eff.eff", {"notes": "TEXT); DROP TABLE x; --"}, [], [])


def test_insert_into_a_missing_table(db):
    with pytest.raises(Exception, match=r"\[PJDB-007\]"):
        db.insert_measurement_data("no_such_table", {}, [{"vin": 1.0}])
    with pytest.raises(Exception, match=r"\[PJDB-008\]"):
        db.get_table_data("no_such_table")
