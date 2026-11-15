# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

"""Tool to set up and use GPIB adapters (menu *Tools* > *GPIB adapters*).

A thin layer over ``ola.gpib_adapter`` (which does the work and is tested without a screen). On the
left the configured adapters (Keysight 82357B, NI GPIB-USB-HS, Prologix, AR488...: several can be
configured together; *Detect* proposes the ones that look connected). On the right, for the
selected adapter:

* **Adapter**: model, VISA board number (``GPIBn``) or serial port / network address, VISA
  library, timeouts, addresses to scan, identification commands;
* **Check**: is the driver installed, is the adapter connected, is its firmware loaded, with what
  to install on this system;
* **Bus**: scan the bus and list the instruments that answer, with the address to use in the
  project (*Copy address*); Interface Clear and the REN line;
* **Console**: send a command typed by the user to an address and read the answer;
* **Linux set-up** (on Linux, for adapters driven by linux-gpib such as a new Keysight 82357B):
  each step (linux-gpib, kernel module, fxload and firmware, udev rule, ``/etc/gpib.conf``, gpib
  group, Python bindings) checked, and the missing ones done as administrator through ``pkexec``
  with a script the user can read first (``ola/gpib_linux.py``).

The configuration is saved in the application settings (``frontend/core/gpib_settings.py``); the
address editor of the instruments uses it. Slow operations (check, scan) run in a thread. Strings:
``frontend/lang/modules/gpib/<lang>.json``.
"""

import logging
import os
import sys
import threading
from typing import Any, Callable, List, Optional

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from frontend.core import gpib_settings
from frontend.core.errorhandler import handle_error
from frontend.ui.module_translator import CatalogTranslator
from ola import gpib_adapter as ga
from ola import gpib_linux as gl
from ola.errors import TransportError
from ola.gpib_adapter import FAMILY_VISA, GpibAdapterConfig, GpibError

log = logging.getLogger(__name__)

LEVEL_MARK = {"ok": "✔", "info": "ℹ", "warn": "⚠", "error": "✖"}
BACKEND_KEYS = (("", "gpb_backend_default"), ("@py", "gpb_backend_py"), ("@ivi", "gpb_backend_ivi"))


class _Worker(QThread):
    """Runs ``func(progress)`` in a thread; ``progress(a, b, c)`` emits ``progressed``."""

    progressed = pyqtSignal(int, int, int)
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(object)

    def __init__(self, func: Callable[[Callable[[int, int, int], None]], Any], parent=None):
        super().__init__(parent)
        self._func = func

    def run(self):
        try:
            self.succeeded.emit(self._func(self.progressed.emit))
        except (GpibError, TransportError, OSError, ValueError) as exc:
            self.failed.emit(exc)


class GpibAdapterDialog(QDialog):
    """The GPIB adapters window (see the module docstring)."""

    linux_line = pyqtSignal(str)  # a line of output of the Linux set-up (from its thread)

    def __init__(
        self,
        translator=None,
        parent=None,
        settings=None,
        rm_factory=None,
        asynchronous: bool = True,
        platform: str = sys.platform,
        probe=None,
        runner=None,
        confirm=None,
    ):
        """``settings``: a ``QSettings`` (default: the application's); ``rm_factory(backend)``
        replaces ``pyvisa.ResourceManager`` and ``asynchronous=False`` runs the slow operations
        directly (tests). Linux set-up: ``platform``, ``probe`` (``ola.gpib_linux.SystemProbe``),
        ``runner`` (runs a command, see ``ola.gpib_linux.default_runner``) and ``confirm(text)``
        (asks before changing the system) replace the real ones in the tests."""
        super().__init__(parent)
        self.tr_ = CatalogTranslator("gpib", translator)
        self._settings = settings
        self._engine_kw = {"rm_factory": rm_factory} if rm_factory is not None else {}
        self.asynchronous = asynchronous
        self._worker: Optional[_Worker] = None
        self._cancel = threading.Event()
        self._console = None  # (adapter name, address, connection) kept open between commands
        self._loading = False
        # nothing is added on its own: only the saved adapters, or those detected when none is saved
        self.adapters: List[GpibAdapterConfig] = gpib_settings.load_adapters(settings)
        first_detection = not self.adapters
        if first_detection:
            try:
                self.adapters = list(ga.detect_adapters([], **self._engine_kw))
            except Exception as exc:  # no VISA library, no serial ports...: start empty
                log.debug("GPIB adapter detection failed: %s", exc)
                self.adapters = []
        self.devices: List[ga.BusDevice] = []
        self.platform = platform
        self._probe = probe
        self._runner = runner or gl.default_runner
        self._confirm = confirm or self._ask_confirmation
        self._firmware_dir = ""
        self.linux_report: Optional[gl.LinuxSetupReport] = None

        self.setWindowTitle(self._t("gpb_title"))
        self.resize(980, 620)
        self._build()
        self._fill_list()
        self.adapter_list.setCurrentRow(0)
        self._update_empty_state()
        if first_detection:
            self._set_status(
                self._t("gpb_detected", count=len(self.adapters)) if self.adapters
                else self._t("gpb_none_configured")
            )

    def _t(self, key: str, **values) -> str:
        return self.tr_.t(key, **values)

    # ----- layout -------------------------------------------------------------------------------
    def _build(self):
        root = QHBoxLayout(self)
        split = QSplitter()
        root.addWidget(split)

        left = QWidget()
        lv = QVBoxLayout(left)
        lv.addWidget(QLabel(self._t("gpb_adapters")))
        self.adapter_list = QListWidget()
        self.adapter_list.currentRowChanged.connect(self._on_adapter_selected)
        lv.addWidget(self.adapter_list)
        row = QHBoxLayout()
        self.add_button = QPushButton(self._t("gpb_add"))
        self.add_button.clicked.connect(self.add_adapter)
        self.remove_button = QPushButton(self._t("gpb_remove"))
        self.remove_button.clicked.connect(self.remove_adapter)
        row.addWidget(self.add_button)
        row.addWidget(self.remove_button)
        lv.addLayout(row)
        self.detect_button = QPushButton(self._t("gpb_detect"))
        self.detect_button.setToolTip(self._t("gpb_detect_tip"))
        self.detect_button.clicked.connect(self.detect)
        lv.addWidget(self.detect_button)
        split.addWidget(left)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_config_tab(), self._t("gpb_tab_adapter"))
        self.tabs.addTab(self._build_check_tab(), self._t("gpb_tab_check"))
        self.tabs.addTab(self._build_bus_tab(), self._t("gpb_tab_bus"))
        self.tabs.addTab(self._build_console_tab(), self._t("gpb_tab_console"))
        self.linux_tab_index = self.tabs.addTab(self._build_linux_tab(), self._t("gpb_tab_linux"))
        split.addWidget(self.tabs)
        split.setStretchFactor(1, 3)

        bottom = QVBoxLayout()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        bottom.addWidget(self.status)
        close = QPushButton(self._t("gpb_close"))
        close.clicked.connect(self.close)
        bottom.addWidget(close)
        lv.addLayout(bottom)

    def _build_config_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.name_edit = QLineEdit()
        form.addRow(self._t("gpb_name"), self.name_edit)
        self.model_combo = QComboBox()
        for p in ga.PROFILES.values():
            self.model_combo.addItem(p.name, p.id)
        self.model_combo.currentIndexChanged.connect(self._update_family_fields)
        form.addRow(self._t("gpb_model"), self.model_combo)

        self.board_spin = QSpinBox()
        self.board_spin.setRange(0, 31)
        self.board_spin.setToolTip(self._t("gpb_board_tip"))
        self.board_label = QLabel(self._t("gpb_board"))
        form.addRow(self.board_label, self.board_spin)
        self.backend_combo = QComboBox()
        for value, key in BACKEND_KEYS:
            self.backend_combo.addItem(self._t(key), value)
        self.backend_label = QLabel(self._t("gpb_backend"))
        form.addRow(self.backend_label, self.backend_combo)

        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setToolTip(self._t("gpb_port_tip"))
        self.port_label = QLabel(self._t("gpb_port"))
        form.addRow(self.port_label, self.port_combo)

        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 600000)
        self.timeout_spin.setSuffix(" ms")
        form.addRow(self._t("gpb_timeout"), self.timeout_spin)
        self.scan_timeout_spin = QSpinBox()
        self.scan_timeout_spin.setRange(10, 60000)
        self.scan_timeout_spin.setSuffix(" ms")
        self.scan_timeout_spin.setToolTip(self._t("gpb_scan_timeout_tip"))
        form.addRow(self._t("gpb_scan_timeout"), self.scan_timeout_spin)
        rng = QHBoxLayout()
        self.first_spin, self.last_spin = QSpinBox(), QSpinBox()
        for s in (self.first_spin, self.last_spin):
            s.setRange(ga.MIN_ADDRESS, ga.MAX_ADDRESS)
            rng.addWidget(s)
        form.addRow(self._t("gpb_scan_range"), rng)
        self.idn_edit = QLineEdit()
        self.idn_edit.setToolTip(self._t("gpb_idn_tip"))
        form.addRow(self._t("gpb_idn"), self.idn_edit)

        self.notes = QLabel("")
        self.notes.setWordWrap(True)
        form.addRow(self.notes)
        buttons = QHBoxLayout()
        self.save_button = QPushButton(self._t("gpb_save"))
        self.save_button.clicked.connect(self.save)
        self.defaults_button = QPushButton(self._t("gpb_defaults"))
        self.defaults_button.clicked.connect(self.restore_defaults)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.defaults_button)
        form.addRow(buttons)
        return w

    def _build_check_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.check_button = QPushButton(self._t("gpb_check"))
        self.check_button.clicked.connect(self.check)
        v.addWidget(self.check_button)
        self.check_table = QTableWidget(0, 2)
        self.check_table.setHorizontalHeaderLabels(["", self._t("gpb_result")])
        self.check_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.check_table.setWordWrap(True)
        self.check_table.verticalHeader().setVisible(False)
        v.addWidget(self.check_table)
        return w

    def _build_bus_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.scan_button = QPushButton(self._t("gpb_scan"))
        self.scan_button.clicked.connect(self.scan)
        self.cancel_button = QPushButton(self._t("gpb_cancel"))
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel.set)
        row.addWidget(self.scan_button)
        row.addWidget(self.cancel_button)
        self.progress = QProgressBar()
        row.addWidget(self.progress)
        v.addLayout(row)
        self.bus_table = QTableWidget(0, 3)
        self.bus_table.setHorizontalHeaderLabels(
            [self._t("gpb_col_address"), self._t("gpb_col_resource"), self._t("gpb_col_idn")]
        )
        self.bus_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.bus_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.bus_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.bus_table.verticalHeader().setVisible(False)
        self.bus_table.itemSelectionChanged.connect(self._on_device_selected)
        v.addWidget(self.bus_table)
        actions = QHBoxLayout()
        self.copy_button = QPushButton(self._t("gpb_copy"))
        self.copy_button.clicked.connect(self.copy_address)
        self.ifc_button = QPushButton(self._t("gpb_ifc"))
        self.ifc_button.setToolTip(self._t("gpb_ifc_tip"))
        self.ifc_button.clicked.connect(self.interface_clear)
        self.local_button = QPushButton(self._t("gpb_local"))
        self.local_button.setToolTip(self._t("gpb_local_tip"))
        self.local_button.clicked.connect(lambda: self.remote_enable(False))
        for b in (self.copy_button, self.ifc_button, self.local_button):
            actions.addWidget(b)
        v.addLayout(actions)
        return w

    def _build_console_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        row.addWidget(QLabel(self._t("gpb_col_address")))
        self.console_addr = QSpinBox()
        self.console_addr.setRange(ga.MIN_ADDRESS, ga.MAX_ADDRESS)
        self.console_addr.setValue(1)
        row.addWidget(self.console_addr)
        self.command_edit = QLineEdit()
        self.command_edit.setPlaceholderText("*IDN?")
        self.command_edit.returnPressed.connect(self.console_query)
        row.addWidget(self.command_edit, 1)
        self.write_button = QPushButton(self._t("gpb_write"))
        self.write_button.clicked.connect(self.console_write)
        self.query_button = QPushButton(self._t("gpb_query"))
        self.query_button.clicked.connect(self.console_query)
        self.read_button = QPushButton(self._t("gpb_read"))
        self.read_button.clicked.connect(self.console_read)
        for b in (self.write_button, self.query_button, self.read_button):
            row.addWidget(b)
        v.addLayout(row)
        self.console_log = QPlainTextEdit()
        self.console_log.setReadOnly(True)
        v.addWidget(self.console_log)
        return w

    def _build_linux_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        intro = QLabel(self._t("gpb_lx_intro"))
        intro.setWordWrap(True)
        v.addWidget(intro)
        self.linux_table = QTableWidget(0, 2)
        self.linux_table.setHorizontalHeaderLabels(["", self._t("gpb_result")])
        self.linux_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.linux_table.setWordWrap(True)
        self.linux_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.linux_table.verticalHeader().setVisible(False)
        v.addWidget(self.linux_table, 2)
        fw_row = QHBoxLayout()
        self.firmware_button = QPushButton(self._t("gpb_lx_firmware"))
        self.firmware_button.setToolTip(self._t("gpb_lx_firmware_tip"))
        self.firmware_button.clicked.connect(self.choose_firmware_dir)
        self.firmware_label = QLabel(self._t("gpb_lx_firmware_none"))
        self.firmware_label.setWordWrap(True)
        fw_row.addWidget(self.firmware_button)
        fw_row.addWidget(self.firmware_label, 1)
        v.addLayout(fw_row)
        row = QHBoxLayout()
        self.linux_check_button = QPushButton(self._t("gpb_lx_check"))
        self.linux_check_button.clicked.connect(self.linux_check)
        self.linux_script_button = QPushButton(self._t("gpb_lx_script"))
        self.linux_script_button.clicked.connect(self.show_linux_script)
        self.linux_save_button = QPushButton(self._t("gpb_lx_save"))
        self.linux_save_button.clicked.connect(self.save_linux_script)
        self.linux_install_button = QPushButton(self._t("gpb_lx_install"))
        self.linux_install_button.clicked.connect(self.linux_install)
        self.linux_python_button = QPushButton(self._t("gpb_lx_python"))
        self.linux_python_button.clicked.connect(self.linux_python)
        for b in (
            self.linux_check_button,
            self.linux_script_button,
            self.linux_save_button,
            self.linux_install_button,
            self.linux_python_button,
        ):
            row.addWidget(b)
        v.addLayout(row)
        self.linux_log = QPlainTextEdit()
        self.linux_log.setReadOnly(True)
        v.addWidget(self.linux_log, 1)
        self.linux_line.connect(self.linux_log.appendPlainText)
        self._update_linux_buttons()
        return w

    # ----- adapters list -------------------------------------------------------------------------
    def _update_empty_state(self):
        """With no adapter the settings tabs and Remove have nothing to work on."""
        has = bool(self.adapters)
        self.tabs.setEnabled(has)
        self.remove_button.setEnabled(has)

    def _fill_list(self):
        self.adapter_list.blockSignals(True)
        self.adapter_list.clear()
        for c in self.adapters:
            item = QListWidgetItem(f"{c.name}  —  {ga.profile(c.profile).name}")
            self.adapter_list.addItem(item)
        self.adapter_list.blockSignals(False)

    @property
    def current(self) -> Optional[GpibAdapterConfig]:
        row = self.adapter_list.currentRow()
        return self.adapters[row] if 0 <= row < len(self.adapters) else None

    def _on_adapter_selected(self, row: int):
        self._close_console()
        cfg = self.current
        if cfg is None:
            return
        self._loading = True
        self.name_edit.setText(cfg.name)
        self.model_combo.setCurrentIndex(max(0, self.model_combo.findData(cfg.profile)))
        self.board_spin.setValue(cfg.board)
        self.backend_combo.setCurrentIndex(max(0, self.backend_combo.findData(cfg.backend)))
        self._fill_ports(cfg.port)
        self.timeout_spin.setValue(cfg.timeout_ms)
        self.scan_timeout_spin.setValue(cfg.scan_timeout_ms)
        self.first_spin.setValue(cfg.scan_first)
        self.last_spin.setValue(cfg.scan_last)
        self.idn_edit.setText(", ".join(cfg.idn_commands))
        self._loading = False
        self._update_family_fields()
        self.check_table.setRowCount(0)
        self._show_devices(gpib_settings.last_scan(cfg.name))

    def _fill_ports(self, current: str):
        self.port_combo.clear()
        ports = [p[0] for p in ga.list_serial_ports()]
        if current and current not in ports:
            ports.insert(0, current)
        self.port_combo.addItems(ports)
        self.port_combo.setEditText(current)

    def _update_family_fields(self):
        family = ga.PROFILES[self.model_combo.currentData()].family
        visa = family == FAMILY_VISA
        for widget in (self.board_spin, self.board_label, self.backend_combo, self.backend_label):
            widget.setVisible(visa)
        for widget in (self.port_combo, self.port_label):
            widget.setVisible(not visa)
        self.local_button.setEnabled(visa)
        prof = ga.PROFILES[self.model_combo.currentData()]
        linux = f" · linux-gpib: {prof.linux_driver}" if prof.linux_driver else ""
        ids = ", ".join(f"{v:04x}:{p:04x}" for v, p in prof.usb_ids)
        self.notes.setText(
            self._t("gpb_notes", family=self._t(f"gpb_family_{family}"), ids=ids or "-") + linux
        )
        if hasattr(self, "linux_tab_index"):
            shown = gl.supports_linux_setup(
                GpibAdapterConfig(profile=prof.id, port="-"), self.platform
            )
            self.tabs.setTabVisible(self.linux_tab_index, shown)
            if not self._loading:
                self.linux_report = None
                self.linux_table.setRowCount(0)
                self._update_linux_buttons()

    def form_config(self) -> GpibAdapterConfig:
        """The configuration as shown in the form (not validated)."""
        commands = [c.strip() for c in self.idn_edit.text().split(",") if c.strip()]
        return GpibAdapterConfig(
            name=self.name_edit.text().strip(),
            profile=self.model_combo.currentData(),
            board=self.board_spin.value(),
            port=self.port_combo.currentText().strip(),
            backend=self.backend_combo.currentData(),
            timeout_ms=self.timeout_spin.value(),
            scan_timeout_ms=self.scan_timeout_spin.value(),
            scan_first=self.first_spin.value(),
            scan_last=self.last_spin.value(),
            idn_commands=commands,
        )

    def _apply_form(self) -> Optional[GpibAdapterConfig]:
        """Validate the form into the selected adapter; None (and a message) if not valid."""
        row = self.adapter_list.currentRow()
        if row < 0:
            return None
        cfg = self.form_config()
        others = [c for i, c in enumerate(self.adapters) if i != row]
        try:
            cfg.validate()
            ga.check_unique_names(others + [cfg])
        except GpibError as exc:
            self._error(exc, "gpb_invalid")
            return None
        old = self.adapters[row]
        if old.name != cfg.name:
            gpib_settings.remember_scan(cfg.name, gpib_settings.last_scan(old.name))
        self.adapters[row] = cfg
        self.adapter_list.item(row).setText(f"{cfg.name}  —  {ga.profile(cfg.profile).name}")
        return cfg

    def save(self) -> bool:
        """Save every adapter in the application settings."""
        if not self.adapters:
            gpib_settings.save_adapters([], self._settings)
            self._set_status(self._t("gpb_saved"))
            return True
        if self._apply_form() is None:
            return False
        try:
            gpib_settings.save_adapters(self.adapters, self._settings)
        except GpibError as exc:
            self._error(exc, "gpb_invalid")
            return False
        self._set_status(self._t("gpb_saved"))
        return True

    def _autosave(self):
        """Save on closing when the form is valid (no message if it is not)."""
        if not self.adapters:  # nothing configured: nothing to keep (and nothing is invented)
            try:
                gpib_settings.save_adapters([], self._settings)
            except GpibError:
                pass
            return
        cfg = self.form_config()
        row = self.adapter_list.currentRow()
        try:
            cfg.validate()
            if row >= 0:
                others = [c for i, c in enumerate(self.adapters) if i != row]
                ga.check_unique_names(others + [cfg])
                self.adapters[row] = cfg
            gpib_settings.save_adapters(self.adapters, self._settings)
        except GpibError:
            pass  # not valid: the user did not save it, nothing to keep

    def restore_defaults(self):
        """Put the default values of the selected model in the form (name and port kept)."""
        cfg = self.form_config()
        fresh = GpibAdapterConfig(name=cfg.name, profile=cfg.profile, port=cfg.port)
        row = self.adapter_list.currentRow()
        self.adapters[row] = fresh
        self._on_adapter_selected(row)

    def add_adapter(self, cfg: Optional[GpibAdapterConfig] = None):
        """Add an adapter (a new Keysight 82357B on the first free board if none is given)."""
        if not isinstance(cfg, GpibAdapterConfig):
            boards = {c.board for c in self.adapters if c.family == FAMILY_VISA}
            board = next(b for b in range(32) if b not in boards)
            cfg = GpibAdapterConfig(name=ga.unique_name(f"GPIB{board}", self.adapters), board=board)
        self.adapters.append(cfg)
        self._fill_list()
        self.adapter_list.setCurrentRow(len(self.adapters) - 1)
        self._update_empty_state()

    def remove_adapter(self):
        row = self.adapter_list.currentRow()
        if row < 0 or row >= len(self.adapters):
            return
        del self.adapters[row]
        self._fill_list()
        self.adapter_list.setCurrentRow(min(row, len(self.adapters) - 1))
        self._update_empty_state()
        if not self.adapters:
            self._set_status(self._t("gpb_none_configured"))

    def detect(self):
        """Add the adapters that look connected and are not configured yet."""
        found = ga.detect_adapters(self.adapters, **self._engine_kw)
        for cfg in found:
            self.adapters.append(cfg)
        if found:
            self._fill_list()
            self.adapter_list.setCurrentRow(len(self.adapters) - len(found))
            self._update_empty_state()
            self._set_status(self._t("gpb_detected", count=len(found)))
        else:
            self._set_status(self._t("gpb_detected_none"))

    # ----- check ---------------------------------------------------------------------------------
    def check(self):
        cfg = self._apply_form()
        if cfg is None:
            return
        self._set_status(self._t("gpb_checking"))
        self._run(
            lambda progress: ga.check_environment(cfg, **self._engine_kw),
            self._show_check,
            "gpb_check_failed",
        )

    def _show_check(self, items: List[ga.DiagItem]):
        self.check_table.setRowCount(0)
        for item in items:
            r = self.check_table.rowCount()
            self.check_table.insertRow(r)
            self.check_table.setItem(r, 0, QTableWidgetItem(LEVEL_MARK.get(item.level, "")))
            text = self._t(item.key, **item.values) if item.key in ga.MESSAGES else item.text
            self.check_table.setItem(r, 1, QTableWidgetItem(text))
        self.check_table.resizeRowsToContents()
        self._set_status(self._t(f"gpb_overall_{ga.worst_level(items)}"))

    # ----- bus -----------------------------------------------------------------------------------
    def scan(self):
        cfg = self._apply_form()
        if cfg is None:
            return
        self._close_console()
        self._cancel.clear()
        self.cancel_button.setEnabled(True)
        self.scan_button.setEnabled(False)
        self.progress.setRange(0, cfg.scan_last - cfg.scan_first + 1)
        self.progress.setValue(0)

        def job(progress):
            return ga.scan_bus(cfg, progress, self._cancel, **self._engine_kw)

        def done(devices):
            gpib_settings.remember_scan(cfg.name, devices)
            self._show_devices(devices)
            text = "gpb_scan_done" if devices else "gpb_scan_empty"
            self._set_status(self._t(text, count=len(devices), adapter=cfg.name))

        self._run(job, done, "gpb_scan_failed", self._on_scan_progress, self._scan_finished)

    def _on_scan_progress(self, address: int, done: int, total: int):
        self.progress.setMaximum(total)
        self.progress.setValue(done)
        if address >= 0:
            self._set_status(self._t("gpb_scanning", address=address))

    def _scan_finished(self):
        self.cancel_button.setEnabled(False)
        self.scan_button.setEnabled(True)

    def _show_devices(self, devices: List[ga.BusDevice]):
        self.devices = list(devices)
        self.bus_table.setRowCount(0)
        for d in devices:
            r = self.bus_table.rowCount()
            self.bus_table.insertRow(r)
            idn = d.idn or self._t("gpb_no_idn")
            for col, text in enumerate((str(d.address), d.resource, idn)):
                self.bus_table.setItem(r, col, QTableWidgetItem(text))
        self.bus_table.resizeColumnsToContents()

    def selected_device(self) -> Optional[ga.BusDevice]:
        rows = {i.row() for i in self.bus_table.selectedItems()}
        return self.devices[min(rows)] if rows else None

    def _on_device_selected(self):
        device = self.selected_device()
        if device is not None:
            self.console_addr.setValue(device.address)

    def copy_address(self):
        device = self.selected_device()
        if device is None:
            self._set_status(self._t("gpb_select_device"))
            return
        QApplication.clipboard().setText(device.resource)
        self._set_status(self._t("gpb_copied", address=device.resource))

    def interface_clear(self):
        cfg = self._apply_form()
        if cfg is None:
            return
        self._close_console()
        try:
            ga.interface_clear(cfg, **self._engine_kw)
        except (GpibError, TransportError) as exc:
            self._error(exc, "gpb_bus_failed")
            return
        self._set_status(self._t("gpb_ifc_done"))

    def remote_enable(self, on: bool):
        cfg = self._apply_form()
        if cfg is None:
            return
        try:
            ga.remote_enable(cfg, on, **self._engine_kw)
        except GpibError as exc:
            self._error(exc, "gpb_bus_failed")
            return
        self._set_status(self._t("gpb_local_done"))

    # ----- console -------------------------------------------------------------------------------
    def _connection(self):
        cfg = self.current
        address = self.console_addr.value()
        if self._console is not None and self._console[:2] == (cfg.name, address):
            return self._console[2]
        self._close_console()
        conn = ga.open_device(cfg, address, **self._engine_kw)
        self._console = (cfg.name, address, conn)
        return conn

    def _close_console(self):
        if self._console is not None:
            conn, self._console = self._console[2], None
            conn.close()

    def _console_do(self, action: Callable[[Any, str], Optional[str]]):
        if self._apply_form() is None:
            return
        command = self.command_edit.text()
        address = self.console_addr.value()
        try:
            answer = action(self._connection(), command)
        except (GpibError, TransportError) as exc:
            self._close_console()
            self.console_log.appendPlainText(f"[{address}] ✖ {exc}")
            return
        if command and action is not _read:
            self.console_log.appendPlainText(f"[{address}] → {command}")
        if answer is not None:
            self.console_log.appendPlainText(f"[{address}] ← {answer}")

    def console_write(self):
        self._console_do(lambda conn, cmd: conn.send(cmd))

    def console_query(self):
        self._console_do(lambda conn, cmd: conn.query(cmd))

    def console_read(self):
        self._console_do(_read)

    # ----- Linux set-up -----------------------------------------------------------------------
    def linux_check(self):
        """Check every step of the Linux set-up of the selected adapter."""
        cfg = self._apply_form()
        if cfg is None:
            return
        rm_factory = self._engine_kw.get("rm_factory", ga._resource_manager)
        self._set_status(self._t("gpb_checking"))
        self._run(
            lambda progress: gl.check_linux_setup(cfg, self._probe, rm_factory),
            self._show_linux,
            "gpb_check_failed",
        )

    def _show_linux(self, report: gl.LinuxSetupReport):
        self.linux_report = report
        self.linux_table.setRowCount(0)
        marks = {gl.OK: "✔", gl.MISSING: "✖", gl.WARN: "⚠", gl.INFO: "ℹ"}
        for step in report.steps:
            r = self.linux_table.rowCount()
            self.linux_table.insertRow(r)
            self.linux_table.setItem(r, 0, QTableWidgetItem(marks.get(step.status, "")))
            self.linux_table.setItem(r, 1, QTableWidgetItem(self._t(step.key, **step.values)))
        self.linux_table.resizeRowsToContents()
        self._update_linux_buttons()
        todo = report.root_fixes or report.needs_python
        self._set_status(self._t("gpb_lx_overall_todo" if todo else "gpb_lx_overall_ok"))

    def _update_linux_buttons(self):
        report = self.linux_report
        root = bool(report and report.root_fixes)
        self.linux_install_button.setEnabled(root)
        self.linux_script_button.setEnabled(root)
        self.linux_save_button.setEnabled(root)
        self.linux_python_button.setEnabled(bool(report and report.needs_python))

    def choose_firmware_dir(self):
        """A folder that already holds the firmware files (when they cannot be downloaded)."""
        folder = QFileDialog.getExistingDirectory(self, self._t("gpb_lx_firmware"))
        if folder:
            self._firmware_dir = folder
            self.firmware_label.setText(folder)

    def linux_script(self) -> str:
        """The script of the missing steps ('' if there is nothing to do as administrator)."""
        if self.linux_report is None:
            return ""
        return gl.build_setup_script(self.linux_report, self._firmware_dir)

    def show_linux_script(self):
        self.linux_log.setPlainText(self.linux_script())

    def save_linux_script(self):
        path, _ = QFileDialog.getSaveFileName(
            self, self._t("gpb_lx_save"), "ola-gpib-setup.sh", "Shell (*.sh)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.linux_script())
            os.chmod(path, 0o755)
        except OSError as exc:
            self._error(exc, "gpb_lx_failed")
            return
        self._set_status(self._t("gpb_lx_saved", path=path))

    def _ask_confirmation(self, text: str) -> bool:
        answer = QMessageBox.question(self, self._t("gpb_lx_install"), text)
        return answer == QMessageBox.StandardButton.Yes

    def linux_install(self):
        """Do the missing steps as administrator (pkexec asks for the password)."""
        report = self.linux_report
        script = self.linux_script()
        if report is None or not script:
            self._set_status(self._t("lx_not_needed"))
            return
        steps = "\n".join("• " + self._t(f"gpb_fix_{f}") for f in report.root_fixes)
        if not self._confirm(self._t("gpb_lx_confirm", steps=steps)):
            return
        self.linux_log.clear()
        self.linux_install_button.setEnabled(False)
        self._set_status(self._t("gpb_lx_running"))

        def done(code):
            self._set_status(self._t("gpb_lx_done"))
            self.linux_check()

        self._run(
            lambda progress: gl.run_setup(script, self.linux_line.emit, self._runner),
            done,
            "gpb_lx_failed",
            on_finished=self._update_linux_buttons,
        )

    def linux_python(self):
        """Install the Python bindings (gpib-ctypes) with pip, as the user."""
        self.linux_log.clear()

        def done(code):
            self._set_status(self._t("gpb_lx_python_done"))
            self.linux_check()

        self._run(
            lambda progress: gl.install_python_bindings(self.linux_line.emit, self._runner),
            done,
            "gpb_lx_failed",
        )

    # ----- helpers -------------------------------------------------------------------------------
    def _run(self, job, on_done, error_key, on_progress=None, on_finished=None):
        """Run ``job(progress)`` in a thread (or directly when not asynchronous)."""
        if not self.asynchronous:
            try:
                result = job(on_progress or (lambda *a: None))
            except (GpibError, TransportError, OSError, ValueError) as exc:
                self._error(exc, error_key)
            else:
                on_done(result)
            finally:
                if on_finished:
                    on_finished()
            return
        worker = _Worker(job, self)
        if on_progress:
            worker.progressed.connect(on_progress)
        worker.succeeded.connect(on_done)
        worker.failed.connect(lambda exc: self._error(exc, error_key))
        if on_finished:
            worker.finished.connect(on_finished)
        self._worker = worker
        worker.start()

    def _set_status(self, text: str):
        self.status.setText(text)

    def _error(self, exc: Exception, key: str):
        text = self._t(key, error=str(exc))
        self._set_status(text)
        handle_error(exc, text)

    def closeEvent(self, event):
        self._autosave()
        self._cancel.set()
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(10000)
        self._close_console()
        super().closeEvent(event)


def _read(conn, command):
    return conn.read_line()
