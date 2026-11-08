# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""The trend window of a cable (no screen needed): its loss against the date, from its runs."""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from frontend.ui.AssetsDialog import AssetHistoryDialog  # noqa: E402
from frontend.ui.TrendDialog import TrendDialog  # noqa: E402
from ola.assets import Asset, history  # noqa: E402
from ola.registry import default_registry  # noqa: E402
from tests.test_trend import CODE, cable_run  # noqa: E402

LOSSES = (("20260101_100000", 0.60), ("20260401_100000", 0.65),
          ("20260701_100000", 0.72), ("20261001_100000", 0.80))  # fmt: skip


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def registry():
    return default_registry(user_dir="/nonexistent")


@pytest.fixture
def runs(registry, tmp_path):
    folder = tmp_path / "runs"
    for stamp, loss in LOSSES:
        cable_run(registry, folder, stamp, loss)
    return folder


def test_the_window_shows_the_trend_of_the_worst_loss(app, runs):
    d = TrendDialog(CODE, [runs], name="RG58 #3")
    assert CODE in d.windowTitle() and "RG58 #3" in d.windowTitle()
    assert d.figure_box.currentData() == "max_loss_db"
    keys = [d.figure_box.itemData(i) for i in range(d.figure_box.count())]
    assert "loss_868MHz_db" in keys
    assert d.result.verdict == "PASS" and len(d.result.points) == 4
    names = [c[0] for c in d.plot.curves]
    assert names == [d._t("ast_t_measured"), d._t("ast_t_line")]
    assert d.plot.curves[0][1][0] == 0 and d.plot.curves[0][1][-1] > 250  # days since the first
    assert "max_loss_db: PASS" in d.text.toPlainText() and d.csv_btn.isEnabled()
    d.close()


def test_a_limit_and_a_rate_give_the_verdict(app, runs):
    d = TrendDialog(CODE, [runs])
    d.figure_box.setCurrentIndex(d.figure_box.findData("loss_868MHz_db"))
    last = d.update_trend().last
    d.limit_on.setChecked(True)
    d.limit.setValue(last + 0.2)
    d.warn_on.setChecked(True)
    d.warn.setValue(3650)
    assert d.result.verdict == "WARNING" and d.result.limit_date is not None
    limit = d.limit.value()  # rounded to the decimals of the box
    assert d.plot.limits and d.plot.limits[0][2] == [limit, limit]
    assert d.plot.curves[1][1][-1] > d.plot.curves[0][1][-1]  # the line goes on to the limit
    d.rate_on.setChecked(True)
    d.rate.setValue(0.01)
    assert d.result.verdict == "FAIL" and "per year" in d.text.toPlainText()
    d.limit.setValue(last - 0.1)
    assert "past the limit" in d.text.toPlainText()
    assert d.options()["higher_is_worse"] is True
    d.lower_worse.setChecked(True)
    assert d.options()["higher_is_worse"] is False
    d.close()


def test_a_cable_with_no_measurement_says_so(app, tmp_path):
    d = TrendDialog("CBL-9999", [tmp_path])
    assert d.figure_box.count() == 0 and d.result is None and "CBL-9999" in d.text.toPlainText()
    assert not d.csv_btn.isEnabled() and d.plot.curves == []
    d.close()


def test_the_series_is_saved_as_csv(app, runs, tmp_path, monkeypatch):
    d = TrendDialog(CODE, [runs])
    out = tmp_path / "trend.csv"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), ""))
    )
    d.export_csv()
    assert out.read_text(encoding="utf-8").splitlines()[0] == "date,value,run"
    assert str(out) in d.text.toPlainText()
    d.close()


def test_the_history_of_the_cable_opens_it(app, runs):
    asset = Asset(CODE, "cable", "RG58 #3", "", {}, created="2026-01-01")
    h = AssetHistoryDialog(asset, history(CODE, [runs]))
    assert h.trend_btn.isEnabled() and h.run_dirs == [str(runs)]
    h.show_trend()
    assert isinstance(h.trend_tool, TrendDialog) and len(h.trend_tool.result.points) == 4
    h.trend_tool.close()
    h.close()
    empty = AssetHistoryDialog(asset, [])
    assert not empty.trend_btn.isEnabled()
    empty.close()
