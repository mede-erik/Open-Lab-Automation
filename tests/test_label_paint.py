"""Painting labels: image, PDF and the exact modules of the QR code (no screen needed)."""

import re

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtGui import QColor  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from frontend.ui.label_paint import render_image, write_pdf  # noqa: E402
from ola.assets import Asset  # noqa: E402
from ola.labels import PRESETS, QR, SHEETS, build_drawing, sheet_drawings  # noqa: E402

CABLE = Asset(
    "CBL-0042", "cable", "RG316 SMA-SMA", "1 m test lead", {"length_m": 1.0}, created="2026-11-03"
)


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def dark(image, x, y):
    return QColor(image.pixel(int(x), int(y))).lightness() < 128


def test_the_image_has_the_size_of_the_label_at_the_resolution(app):
    image = render_image(build_drawing(PRESETS["50x25"], CABLE), dpi=300)
    assert (image.width(), image.height()) == (591, 295)  # 50 x 25 mm at 300 dpi
    assert image.dotsPerMeterX() == pytest.approx(11811, abs=2)
    small = render_image(build_drawing(PRESETS["50x25"], CABLE), dpi=100)
    assert (small.width(), small.height()) == (197, 98)


def test_every_module_of_the_qr_code_is_painted_where_it_belongs(app):
    d = build_drawing(PRESETS["50x25"], CABLE)
    qr = next(i for i in d.items if isinstance(i, QR))
    dpi = 600
    scale = dpi / 25.4
    image = render_image(d, dpi)
    wrong = 0
    for r, row in enumerate(qr.matrix):
        for c, expected in enumerate(row):
            cx = (qr.x + (c + 0.5) * qr.module) * scale
            cy = (qr.y + (r + 0.5) * qr.module) * scale
            wrong += dark(image, cx, cy) != expected
    assert wrong == 0  # all 441 modules: the code is exactly what segno made, so a scanner reads it


def test_the_quiet_zone_around_the_qr_is_white(app):
    d = build_drawing(PRESETS["50x25"], CABLE)
    qr = next(i for i in d.items if isinstance(i, QR))
    image = render_image(d, 300)
    scale = 300 / 25.4
    for dx in (-1.2, qr.size + 0.6):  # a strip left and right of the code, inside the label
        x = (qr.x + dx) * scale
        assert not any(dark(image, x, (qr.y + t * qr.size) * scale) for t in (0.1, 0.5, 0.9))


def test_the_text_is_painted(app):
    image = render_image(build_drawing(PRESETS["50x25"], CABLE), 300)
    d = build_drawing(PRESETS["50x25"], CABLE)
    code = next(t for t in d.items if getattr(t, "text", "") == "CBL-0042")
    scale = 300 / 25.4
    top, bottom = int((code.y - code.size) * scale), int(code.y * scale)
    left, right = int(code.x * scale), int((code.x + 12) * scale)
    inked = sum(dark(image, x, y) for x in range(left, right, 2) for y in range(top, bottom, 2))
    assert inked > 50  # there is ink where the code is written


def test_a_pdf_has_one_page_per_drawing_at_the_real_size(app, tmp_path):
    pdf = tmp_path / "labels.pdf"
    one = build_drawing(PRESETS["50x25"], CABLE)
    write_pdf(str(pdf), [one])
    data = pdf.read_bytes()
    assert (
        data.startswith(b"%PDF") and data.count(b"/Type /Page\n") + data.count(b"/Type /Page ") >= 1
    )
    box = re.search(rb"/MediaBox \[0 0 ([\d.]+) ([\d.]+)\]", data)
    assert float(box.group(1)) == pytest.approx(50 / 25.4 * 72, abs=0.6)  # 141.7 points
    assert float(box.group(2)) == pytest.approx(25 / 25.4 * 72, abs=0.6)


def test_a_sheet_pdf_is_a4_with_several_pages(app, tmp_path):
    cards = [Asset(f"CBL-{n:04d}", "cable", f"c{n}", created="2026-01-01") for n in range(1, 30)]
    pages = sheet_drawings(SHEETS["A4 3x8 (70x37)"], PRESETS["50x25"], cards)
    pdf = tmp_path / "sheet.pdf"
    write_pdf(str(pdf), pages)
    data = pdf.read_bytes()
    assert len(re.findall(rb"/Type /Page\b(?!s)", data)) == 2  # 29 labels: two sheets of 24
    box = re.search(rb"/MediaBox \[0 0 ([\d.]+) ([\d.]+)\]", data)
    assert float(box.group(1)) == pytest.approx(210 / 25.4 * 72, abs=0.6)


def test_there_must_be_something_to_write(app, tmp_path):
    with pytest.raises(ValueError, match="no label"):
        write_pdf(str(tmp_path / "x.pdf"), [])


@pytest.mark.parametrize("bold", [False, True])
def test_the_width_estimate_is_never_less_than_the_real_text_width(app, bold):
    """Text that the layout says fits must really fit, whatever the system font is."""
    from PyQt6.QtGui import QFont, QFontMetricsF

    from frontend.ui.label_paint import FONT_FAMILY
    from ola.labels import text_width

    samples = [
        "CBL-0042", "RG316 SMA-SMA", "LMR195 N-SMA", "1 m low-loss test lead", "868 MHz whip",
        "MMMMMMMM", "WWWWW", "iiiiiiii", "0.6 dB @ 868MHz, 2026-11-03", "Semi-rigid 0.141 SMA-SMA",
        "RF lab", "S/N X123", "calibrated with the VNA on the left bench",
    ]  # fmt: skip
    font = QFont(FONT_FAMILY)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    font.setPixelSize(100)
    font.setBold(bold)
    metrics = QFontMetricsF(font)
    for text in samples:
        real = metrics.horizontalAdvance(text) / 100  # in units of the font size
        assert text_width(text, 1.0, bold) >= real, (text, text_width(text, 1.0, bold), real)
        assert text_width(text, 1.0, bold) <= real * 1.6  # and not absurdly wasteful
