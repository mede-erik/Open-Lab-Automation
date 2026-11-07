# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Labels for cables and devices: layout, QR code, SVG, sheets."""

import re
import xml.etree.ElementTree as ET

import pytest

from ola.assets import Asset, qr_text
from ola.labels import (
    FIELDS,
    LabelSpec,
    MIN_MODULE_MM,
    PRESETS,
    QR,
    SHEETS,
    Box,
    Drawing,
    Line,
    Text,
    build_drawing,
    field_text,
    fit_text,
    qr_matrix,
    render_svg,
    sheet_drawings,
    text_width,
)

CABLE = Asset(
    "CBL-0042", "cable", "RG316 SMA-SMA", "1 m low-loss test lead",
    attributes={"length_m": 1.0, "connectors": "SMA - SMA"}, created="2026-11-03",
    owner="RF lab", serial="X123", notes="calibrated with the VNA on the left bench",
)  # fmt: skip


def texts(drawing):
    return [i for i in drawing.items if isinstance(i, Text)]


def qr_of(drawing):
    return next(i for i in drawing.items if isinstance(i, QR))


# ---- the text of each line ----------------------------------------------------------------------
@pytest.mark.parametrize(
    "key,text",
    [
        ("id", "CBL-0042"), ("name", "RG316 SMA-SMA"), ("description", "1 m low-loss test lead"),
        ("connectors", "SMA - SMA"), ("length", "1 m"), ("date", "2026-11-03"), ("owner", "RF lab"),
        ("serial", "S/N X123"), ("notes", "calibrated with the VNA on the left bench"),
        ("last_measurement", ""), ("nonsense", ""),
    ],
)  # fmt: skip
def test_the_text_of_a_line(key, text):
    assert field_text(key, CABLE) == text
    assert field_text("last_measurement", CABLE, "0.6 dB @ 868 MHz") == "0.6 dB @ 868 MHz"


def test_a_card_without_a_value_has_no_line():
    bare = Asset("ANT-0001", "antenna", "whip")
    assert [field_text(k, bare) for k in ("length", "connectors", "serial", "owner")] == [""] * 4
    assert field_text("length", Asset("A", "cable", "x", attributes={"length_m": 2.5})) == "2.5 m"


def test_every_field_is_listed_in_the_order_of_importance():
    assert FIELDS[0] == "id" and FIELDS[-1] == "notes" and len(set(FIELDS)) == len(FIELDS)


# ---- the QR code --------------------------------------------------------------------------------
def test_the_qr_is_a_normal_qr_not_a_micro_one():
    matrix = qr_matrix(qr_text("CBL-0042"))
    assert len(matrix) == 21 and all(len(row) == 21 for row in matrix)  # version 1; micro is 11-17
    for r, c in ((0, 0), (0, 20), (20, 0)):  # the three finder patterns' corners are dark
        assert matrix[r][c] is True


def test_the_qr_holds_the_code_as_the_scanner_will_read_it():
    import segno

    code = segno.make(qr_text(CABLE.id), error="q", micro=False)
    assert [list(map(bool, row)) for row in code.matrix] == qr_matrix("OLA:CBL-0042")
    assert qr_matrix("OLA:CBL-0042") != qr_matrix("OLA:CBL-0043")


# ---- fitting text -------------------------------------------------------------------------------
def test_text_fits_by_shrinking_then_by_cutting():
    size, shown = fit_text("RG316", 30, 3.2)
    assert size == 3.2 and shown == "RG316"
    size, shown = fit_text("a rather long name", 30, 3.2)
    assert 1.8 <= size < 3.2 and text_width(shown, size) <= 30  # smaller, and it fits
    assert shown == "a rather long name"  # not cut
    size, shown = fit_text("a very very long description that cannot ever fit here", 15, 3.2)
    assert size == 1.8 and shown.endswith("…") and text_width(shown, size) <= 15 + size


def test_the_width_estimate_errs_on_the_long_side():
    assert text_width("MMMM", 3.0) > 4 * 3.0 * 0.5  # at least half the size per character
    assert text_width("abc", 3.0, bold=True) > text_width("abc", 3.0)


# ---- a single label -----------------------------------------------------------------------------
def test_a_50x25_label_has_the_qr_on_the_left_and_the_text_on_the_right():
    d = build_drawing(PRESETS["50x25"], CABLE)
    qr = qr_of(d)
    shown = {t.text: t for t in texts(d)}
    assert (
        "CBL-0042" in shown
        and "RG316 SMA-SMA" in shown
        and "1 m" in shown
        and "2026-11-03" in shown
    )
    assert shown["CBL-0042"].bold and shown["CBL-0042"].size > shown["RG316 SMA-SMA"].size
    assert all(t.x > qr.x + qr.size for t in shown.values())  # the text starts after the QR code
    assert qr.module >= MIN_MODULE_MM and d.warnings == [] and d.dropped == []


def test_everything_stays_inside_the_label():
    for name, spec in PRESETS.items():
        d = build_drawing(spec.with_fields(FIELDS), CABLE, "0.6 dB @ 868 MHz")
        for t in texts(d):
            assert 0 <= t.x and t.x + text_width(t.text, t.size, t.bold) <= spec.width_mm + 0.5, (
                name,
                t,
            )
            assert 0 < t.y <= spec.height_mm, (name, t)
        for q in (i for i in d.items if isinstance(i, QR)):
            assert (
                0 <= q.x
                and q.x + q.size <= spec.width_mm
                and 0 <= q.y
                and q.y + q.size <= spec.height_mm
            )


def test_lines_that_do_not_fit_are_dropped_from_the_end_and_reported():
    spec = PRESETS["40x20"].with_fields(FIELDS)  # every line on a small label
    d = build_drawing(spec, CABLE, "0.6 dB @ 868 MHz")
    kept = [t.text for t in texts(d)]
    assert kept[0] == "CBL-0042"  # the code is always kept
    assert d.dropped and d.dropped[0] == "notes"  # the least important goes first
    assert "calibrated" not in " ".join(kept)
    assert len(kept) + len(d.dropped) == 10  # nothing is lost without being reported


def test_a_label_with_only_the_code_always_works():
    d = build_drawing(PRESETS["40x20"].with_fields(["id"], qr=False), CABLE)
    assert [t.text for t in texts(d)] == ["CBL-0042"] and not any(
        isinstance(i, QR) for i in d.items
    )
    big = texts(d)[0]
    assert big.size >= 5  # large and easy to read


def test_a_label_without_a_qr_uses_the_whole_width():
    with_qr = build_drawing(PRESETS["50x25"], CABLE)
    without = build_drawing(PRESETS["50x25"].with_fields(("id", "name"), qr=False), CABLE)
    assert min(t.x for t in texts(without)) < min(t.x for t in texts(with_qr))
    assert not any(isinstance(i, QR) for i in without.items)


def test_a_qr_too_small_to_print_is_flagged():
    tiny = PRESETS["50x25"].with_fields(("id",))
    tiny = type(tiny)("tiny", 14, 9)  # a very small label
    d = build_drawing(tiny, CABLE)
    assert d.warnings and "too small" in d.warnings[0] and str(MIN_MODULE_MM) in d.warnings[0]


def test_the_border_is_drawn_only_when_asked():
    plain = build_drawing(PRESETS["50x25"], CABLE)
    framed = build_drawing(PRESETS["50x25"].__class__("f", 50, 25, border=True), CABLE)
    assert not any(isinstance(i, Box) for i in plain.items)
    assert any(isinstance(i, Box) for i in framed.items)


def test_a_long_name_is_shrunk_not_overflowing():
    long_cable = Asset(
        "CBL-0001",
        "cable",
        "Low-loss semi-rigid test cable with SMA connectors",
        created="2026-01-01",
    )
    d = build_drawing(PRESETS["50x25"], long_cable)
    name = next(t for t in texts(d) if t.text.startswith("Low-loss"))
    assert text_width(name.text, name.size) <= 50 - name.x + 0.5


# ---- a flag for a thin cable --------------------------------------------------------------------
def test_a_flag_repeats_the_text_on_both_sides_of_a_fold():
    d = build_drawing(PRESETS["flag 60x15"], CABLE)
    shown = [t.text for t in texts(d)]
    assert shown.count("CBL-0042") == 2 and shown.count("RG316 SMA-SMA") == 2
    fold = next(i for i in d.items if isinstance(i, Line))
    assert fold.dashed and fold.x1 == fold.x2 == 30
    left = [t for t in texts(d) if t.x < 30]
    right = [t for t in texts(d) if t.x > 30]
    assert len(left) == len(right) == 2
    assert not any(isinstance(i, QR) for i in d.items)


def test_a_narrow_flag_says_it_cannot_have_a_qr():
    narrow = LabelSpec("narrow", 60, 7, layout="flag", fields=("id",), qr=True)
    d = build_drawing(narrow, CABLE)
    assert not any(isinstance(i, QR) for i in d.items)
    assert [t.text for t in texts(d)] == [
        "CBL-0042",
        "CBL-0042",
    ]  # the code is still written, twice
    assert any("this narrow cannot have a QR" in w for w in d.warnings)


def test_a_taller_flag_can_have_the_qr_on_each_side():
    spec = PRESETS["flag 60x15"].__class__(
        "tall", 80, 20, layout="flag", fields=("id", "name"), qr=True
    )
    d = build_drawing(spec, CABLE)
    assert len([i for i in d.items if isinstance(i, QR)]) == 2 and d.warnings == []


# ---- SVG ----------------------------------------------------------------------------------------
def test_the_svg_is_well_formed_and_at_the_real_size():
    svg = render_svg(build_drawing(PRESETS["50x25"], CABLE))
    root = ET.fromstring(svg)
    assert root.attrib["width"] == "50mm" and root.attrib["height"] == "25mm"
    assert root.attrib["viewBox"] == "0 0 50 25"
    ns = {"s": "http://www.w3.org/2000/svg"}
    assert "CBL-0042" in [t.text for t in root.findall("s:text", ns)]
    assert len(root.findall("s:path", ns)) == 1  # the QR code is one path


def test_the_svg_qr_path_draws_exactly_the_modules_of_the_code():
    d = build_drawing(PRESETS["50x25"], CABLE)
    qr = qr_of(d)
    path = ET.fromstring(render_svg(d)).find("{http://www.w3.org/2000/svg}path").attrib["d"]
    dark = set()
    for x, y, run in re.findall(r"M([\d.]+) ([\d.]+)h([\d.]+)v", path):
        col0, row = round((float(x) - qr.x) / qr.module), round((float(y) - qr.y) / qr.module)
        dark |= {(row, col0 + k) for k in range(round(float(run) / qr.module))}
    expected = {(r, c) for r, row in enumerate(qr.matrix) for c, v in enumerate(row) if v}
    assert dark == expected  # not one module more or less


def test_text_is_escaped_in_the_svg():
    tricky = Asset("CBL-0007", "cable", 'A&B <"x">', created="2026-01-01")
    svg = render_svg(build_drawing(PRESETS["50x25"], tricky))
    assert "A&amp;B &lt;" in svg
    ET.fromstring(svg)  # still well formed


def test_the_fold_and_the_border_are_in_the_svg():
    flag = render_svg(build_drawing(PRESETS["flag 60x15"], CABLE))
    assert 'stroke-dasharray="1 1"' in flag
    framed = render_svg(build_drawing(PRESETS["50x25"].__class__("f", 50, 25, border=True), CABLE))
    assert 'fill="none" stroke="black"' in framed


# ---- sheets -------------------------------------------------------------------------------------
def test_a_sheet_has_the_positions_of_its_grid():
    sheet = SHEETS["A4 3x8 (70x37)"]
    assert sheet.per_page == 24 and sheet.position(0) == (0, 0) and sheet.position(1) == (70, 0)
    assert sheet.position(3) == (0, 37) and sheet.position(23) == (140, 259)
    avery = SHEETS["A4 3x7 (63.5x38.1)"]
    assert avery.position(1)[0] == pytest.approx(7.2 + 63.5 + 2.5) and avery.position(0)[1] == 15.1


def test_every_sheet_fits_on_its_page():
    for name, sheet in SHEETS.items():
        right = sheet.position(sheet.cols - 1)[0] + sheet.label_w_mm
        bottom = sheet.position(sheet.per_page - 1)[1] + sheet.label_h_mm
        assert right <= sheet.page_w_mm + 0.01 and bottom <= sheet.page_h_mm + 0.01, name
        assert sheet.label_spec(PRESETS["50x25"]).width_mm == sheet.label_w_mm


def test_labels_are_placed_on_the_sheet_and_the_used_ones_are_skipped():
    sheet = SHEETS["A4 3x8 (70x37)"]
    cards = [Asset(f"CBL-{n:04d}", "cable", f"c{n}", created="2026-01-01") for n in range(1, 4)]
    pages = sheet_drawings(sheet, PRESETS["50x25"], cards, skip=4)
    assert len(pages) == 1 and (pages[0].width, pages[0].height) == (210, 297)
    ids = {t.text: t for t in texts(pages[0]) if t.text.startswith("CBL-")}
    assert (
        ids["CBL-0001"].x > 70 and ids["CBL-0001"].y > 37
    )  # the fifth position: second row, second column
    assert ids["CBL-0002"].x > 140 and ids["CBL-0003"].y > 74


def test_more_labels_than_a_sheet_make_more_pages_and_skip_applies_to_the_first_only():
    sheet = SHEETS["A4 3x8 (70x37)"]
    cards = [Asset(f"CBL-{n:04d}", "cable", f"c{n}", created="2026-01-01") for n in range(1, 30)]
    pages = sheet_drawings(sheet, PRESETS["50x25"], cards, skip=20)
    assert len(pages) == 3
    counts = [len([t for t in texts(p) if t.text.startswith("CBL-")]) for p in pages]
    assert counts == [4, 24, 1]  # 4 free places on the first sheet, then a full one, then the rest
    assert sheet_drawings(sheet, PRESETS["50x25"], []) == []


def test_a_sheet_whose_first_page_is_used_up_starts_on_a_fresh_one():
    sheet = SHEETS["A4 3x8 (70x37)"]
    card = Asset("CBL-0001", "cable", "c", created="2026-01-01")
    pages = sheet_drawings(sheet, PRESETS["50x25"], [card], skip=24)
    assert len(pages) == 1
    assert [t for t in texts(pages[0]) if t.text == "CBL-0001"][0].x < 70  # at the first position


def test_sheet_labels_keep_the_chosen_lines_and_report_problems_by_code():
    sheet = SHEETS["A4 5x13 (38.1x21.2)"]  # small labels
    cards = [CABLE]
    base = PRESETS["50x25"].with_fields(FIELDS)
    page = sheet_drawings(sheet, base, cards, last_measurements={"CBL-0042": "0.6 dB @ 868 MHz"})[0]
    assert any(
        d.startswith("CBL-0042:") for d in page.dropped
    )  # lines were dropped on a small label
    assert isinstance(page, Drawing)
