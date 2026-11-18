# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

import os
import json
import logging
import traceback
try:
    import pyvisa
    PYVISA_AVAILABLE = True
except (ImportError, ValueError) as e:
    pyvisa = None
    PYVISA_AVAILABLE = False
    logging.getLogger('frontend.ui.RemoteControlTab').warning(f"PyVISA not available: {e}")

logger = logging.getLogger('frontend.ui.RemoteControlTab')
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGroupBox, QLineEdit, QPushButton, QHBoxLayout, QCheckBox, QSlider, QScrollArea, QFrame
from frontend.ui.layout_utils import FlowLayout
from PyQt6.QtCore import QEvent, QTimer, Qt
from frontend.core.errorhandler import ErrorHandler
from ola.call_errors import CallNotSupportedError, InstrumentNotConnectedError, StepFailedError
from ola.call_errors import ManualActionCancelledError
from ola.datalogger_setup import datalogger_calls, scan_order
from ola.manual_instrument import manual_handle_from_inst
from ola.datalogger_setup import signature as datalogger_signature
from ola.multimeter_setup import accepts_from, measured_channel, multimeter_calls
from ola.multimeter_setup import signature as multimeter_signature
from frontend.ui.theme_utils import set_class
from frontend.core.errorhandler import show_problem, with_code


# =========================
# RemoteControlTab
# =========================

class RemoteControlTab(QWidget):
    """
    Tab for remote control of instruments.
    For each power supply/electronic load channel, shows a box to set voltage/current.
    On top, a single box shows all measurements from dataloggers/multimeters (oscilloscopes excluded).
    Uses pyvisa for direct communication, using SCPI commands from LoadInstruments.
    """
    _MANUAL_ICON = '\u2699'  # ⚙ gear icon for manual instruments
    _MAX_RETRY_ATTEMPTS = 5   # Stop auto-retrying after this many failed attempts
    _RETRY_BASE_DELAY_MS = 5000  # Initial retry delay in ms; doubles each attempt (capped at 60 s)
    def __init__(self, load_instruments):
        """
        Initialize the RemoteControlTab.
        Sets up the layout, measurement group, and channels container.
        """
        super().__init__()
        self.instruments_manager = load_instruments  # Rinominato per evitare conflitti

        # Initialize logger and error handler
        try:
            from frontend.core.logger import Logger
            self.logger = Logger()
            self.logger.info("RemoteControlTab initialization started")
        except Exception as e:
            print(f"The logger cannot be started: {e}")
            self.logger = None

        # Initialize error handler
        self.error_handler = ErrorHandler()

        if self.instruments_manager is None:
            msg = "WARNING: RemoteControlTab started without LoadInstruments"
            print(msg)
            if self.logger:
                self.logger.error(msg)
        else:
            msg = f"RemoteControlTab started with LoadInstruments: {type(self.instruments_manager)}"
            print(msg)
            if self.logger:
                self.logger.info(msg)

        self.main_layout = QVBoxLayout()
        # Layout orizzontale per titolo e pulsante reload
        top_layout = FlowLayout(spacing=6)  # the buttons wrap when the window is narrow
        self.label = QLabel()  # texts: see _retranslate
        top_layout.addWidget(self.label)
        # Pulsante oscilloscopio con icona
        self.osc_btn = QPushButton()
        osc_icon_path = os.path.join(os.path.dirname(__file__), '../assets/icons/oscilloscope.png')
        print(f"[RemoteControlTab] looking for the oscilloscope icon: {osc_icon_path}")
        if os.path.exists(osc_icon_path):
            from PyQt6.QtGui import QIcon
            from PyQt6.QtCore import QSize
            icon = QIcon(osc_icon_path)
            self.osc_btn.setIcon(icon)
            self.osc_btn.setIconSize(QSize(48, 48))  # Icona 48px dentro pulsante 64px
            print(f"[RemoteControlTab] oscilloscope icon loaded: {osc_icon_path}")
        else:
            self.osc_btn.setText('OSC')
            print("[RemoteControlTab] oscilloscope icon not found, using text")
        self.osc_btn.setFixedSize(64, 64)
        self.osc_btn.clicked.connect(self._configure_oscilloscope_from_was)
        top_layout.addWidget(self.osc_btn)
        # Pulsante reload con icona
        self.reload_btn = QPushButton()
        refresh_icon_path = os.path.join(os.path.dirname(__file__), '../assets/icons/refresh.png')
        print(f"[RemoteControlTab] looking for the refresh icon: {refresh_icon_path}")
        if os.path.exists(refresh_icon_path):
            from PyQt6.QtGui import QIcon
            from PyQt6.QtCore import QSize
            icon = QIcon(refresh_icon_path)
            self.reload_btn.setIcon(icon)
            self.reload_btn.setIconSize(QSize(48, 48))  # Icona 48px dentro pulsante 64px
            print(f"[RemoteControlTab] refresh icon loaded: {refresh_icon_path}")
        else:
            self.reload_btn.setText('↻')
            print("[RemoteControlTab] refresh icon not found, using text")
        self.reload_btn.setFixedSize(64, 64)
        self.reload_btn.clicked.connect(self._reload_instruments_from_mainwindow)
        top_layout.addWidget(self.reload_btn)
        self.main_layout.addLayout(top_layout)
        self.meas_group = QGroupBox()
        self.meas_layout = QVBoxLayout()
        self.meas_group.setLayout(self.meas_layout)
        self.main_layout.addWidget(self.meas_group)
        self.channels_container = QWidget()
        self.channels_layout = QHBoxLayout()  # Cambiato da QVBoxLayout a QHBoxLayout per supportare colonne
        self.channels_container.setLayout(self.channels_layout)
        self.main_layout.addWidget(self.channels_container)

        # Crea le colonne per i canali
        self.left_column = QVBoxLayout()
        self.right_column = QVBoxLayout()
        self.channels_layout.addLayout(self.left_column)
        self.channels_layout.addLayout(self.right_column)
        self.main_layout.addStretch()
        # The content scrolls: with many instruments it is taller than the screen, and without a
        # scroll area it would set a minimum height for the whole window
        content = QWidget()
        content.setLayout(self.main_layout)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        self._scroll = scroll
        self._instrument_items = []  # (widget, channel count) of the instruments, in order
        self._column_count = 1
        scroll.viewport().installEventFilter(self)  # the columns follow the width of the window
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self.current_channel_widgets = []  # Stores references to current channel widgets
        # Initialize VISA resource manager with lazy loading to avoid segmentation fault
        self.rm = None
        self._visa_init_attempted = False
        self.visa_connections = {}  # Stores active VISA connections
        self.meas_labels = {}  # Stores measurement labels for dataloggers
        self.connection_timers = {}  # Stores connection retry timers
        self.connection_retry_counts = {}  # Tracks per-timer retry attempt count
        # Translator is provided later via update_translation() by the shared application state
        self.translator = None
        self._retranslate()

    def _reload_instruments_from_mainwindow(self):
        """Richiama la funzione di reload strumenti dal MainWindow se disponibile."""
        parent = self.parent()
        # Cerca il MainWindow nella gerarchia
        while parent is not None and not hasattr(parent, 'reload_remote_tab_instruments'):
            parent = parent.parent()
        if parent is not None and hasattr(parent, 'reload_remote_tab_instruments'):
            parent.reload_remote_tab_instruments()
        else:
            print("[RemoteControlTab] no MainWindow with reload_remote_tab_instruments.")

    def _configure_oscilloscope_from_was(self):
        """Apply the oscilloscope settings of the project (its first .was file) to every
        oscilloscope of the instrument file. A window appears only if something went wrong (no
        project, no .was, an unreachable instrument, settings the model refused...): when it
        works the settings are seen on the oscilloscope itself."""
        self._scope_report = []
        try:
            self._configure_oscilloscopes()
        finally:
            self._show_scope_report()

    # the code of each problem of the oscilloscope settings (ERROR_CODES.md)
    SCOPE_CODES = {
        "rc_scope_no_project": "PROJ-009",
        "rc_scope_no_was": "PROJ-007",
        "rc_scope_was_missing": "FILE-001",
        "rc_scope_was_unreadable": "FILE-003",
        "rc_scope_none": "INST-005",
        "rc_scope_manual": "INST-001",
        "rc_scope_no_address": "INST-005",
        "rc_scope_no_model": "LIB-003",
        "rc_scope_visa": "VISA-005",
        "rc_scope_connect_failed": "VISA-001",
        "rc_scope_no_answer": "VISA-004",
        "rc_scope_failed": "VISA-003",
        "rc_scope_calls_failed": "CALL-001",
    }

    def _scope_note(self, severity, key, **values):
        """One line of the report of the oscilloscope settings ("ok", "warning" or "error");
        a problem starts with its code."""
        text = self._t(key, **values)
        code = self.SCOPE_CODES.get(key)
        if severity != "ok" and code:
            text = f"[{code}] {text}"
        self._scope_report.append((severity, text))
        print(f"[RemoteControlTab] {text}")
        if self.logger and severity != "ok":
            self.logger.warning(text)

    def _show_scope_report(self):
        report = getattr(self, '_scope_report', [])
        problems = [line for severity, line in report if severity != "ok"]
        if problems:  # nothing to say when everything was applied
            # each line has its own code; the box is the code of the first problem
            first = problems[0][1:problems[0].index("]")] if problems[0].startswith("[") else None
            show_problem(self, self._t("rc_scope_title"), "\n".join(problems), code=first)

    def _configure_oscilloscopes(self):
        parent = self.parent()
        while parent is not None and not hasattr(parent, 'current_project_dir'):
            parent = parent.parent()
        if (parent is None or not getattr(parent, 'current_project_dir', None)
                or not getattr(parent, 'current_project_data', None)):
            self._scope_note("error", "rc_scope_no_project")
            return
        was_files = parent.current_project_data.get('was_files', [])
        if not was_files:
            self._scope_note("error", "rc_scope_no_was")
            return
        was_file = was_files[0]  # the first .was file of the project
        was_path = os.path.join(parent.current_project_dir, was_file)
        if not os.path.exists(was_path):
            self._scope_note("error", "rc_scope_was_missing", file=was_file)
            return
        try:
            with open(was_path, 'r', encoding='utf-8') as f:
                was_data = json.load(f)
        except (OSError, ValueError) as e:
            self._scope_note("error", "rc_scope_was_unreadable", file=was_file, error=e)
            return
        self._apply_oscilloscope_settings(was_data, was_file)

    def _apply_oscilloscope_settings(self, was_data, was_file=""):
        """Apply the settings to every oscilloscope of the instrument file."""
        oscilloscopes = self._get_project_oscilloscopes()
        if not oscilloscopes:
            self._scope_note("error", "rc_scope_none")
            return
        for osc_inst in oscilloscopes:
            name = osc_inst.get('instance_name', 'N/A')
            try:
                self._configure_single_oscilloscope(osc_inst, was_data, was_file)
            except Exception as e:
                self._scope_note("error", "rc_scope_failed", name=name, error=e)

    def _get_project_oscilloscopes(self):
        """Recupera gli oscilloscopi dal file .inst del progetto corrente."""
        parent = self.parent()
        while parent is not None and not hasattr(parent, 'current_project_dir'):
            parent = parent.parent()

        if not parent or not parent.current_project_dir or not parent.current_project_data:
            return []

        inst_file = parent.current_project_data.get('inst_file')
        if not inst_file:
            return []

        inst_path = os.path.join(parent.current_project_dir, inst_file)
        if not os.path.exists(inst_path):
            return []

        try:
            with open(inst_path, 'r', encoding='utf-8') as f:
                inst_data = json.load(f)

            # Filtra solo gli oscilloscopi (gestisce sia 'oscilloscope' che 'oscilloscopes')
            oscilloscopes = []
            print("[RemoteControlTab] instruments of the .inst file:")
            for idx, inst in enumerate(inst_data.get('instruments', [])):
                inst_type = inst.get('instrument_type', '')
                inst_name = inst.get('instance_name', 'N/A')
                print(f"  [{idx}] {inst_name} - type: '{inst_type}'")

                # Gestisce sia 'oscilloscope' che 'oscilloscopes'
                if inst_type in ['oscilloscope', 'oscilloscopes']:
                    oscilloscopes.append(inst)
                    print(f"    → oscilloscope: {inst_name}")

            print(f"[RemoteControlTab] oscilloscopes found: {len(oscilloscopes)}")
            return oscilloscopes
        except Exception as e:
            print(f"[RemoteControlTab] reading the .inst file failed: {e}")
            return []

    def _configure_single_oscilloscope(self, osc_inst, was_data, was_file=""):
        """Connect to one oscilloscope and apply the settings; every problem goes in the report."""
        osc_name = osc_inst.get('instance_name', 'N/A')
        osc_model = osc_inst.get('model', '') or osc_inst.get('model_id', '')
        visa_addr = osc_inst.get('visa_address', '')
        if osc_inst.get('is_manual'):
            self._scope_note("warning", "rc_scope_manual", name=osc_name)
            return
        if not visa_addr:
            self._scope_note("error", "rc_scope_no_address", name=osc_name)
            return
        library = self.instruments_manager.get_library() if self.instruments_manager else None
        model_id = library.resolve_model_id(osc_inst.get('model_id', osc_model)) if library else None
        if not model_id:
            self._scope_note("error", "rc_scope_no_model", name=osc_name, model=osc_model)
            return
        if not self._ensure_visa_initialized():
            self._scope_note("error", "rc_scope_visa", name=osc_name)
            return
        try:
            if visa_addr in self.visa_connections:
                instr = self.visa_connections[visa_addr]
            else:
                instr = self.rm.open_resource(visa_addr)
                self._configure_serial(instr, visa_addr, osc_inst)
                self.visa_connections[visa_addr] = instr
        except Exception as e:
            self._scope_note(
                "error", "rc_scope_connect_failed", name=osc_name, address=visa_addr, error=e)
            return
        executor = self._get_instrument_executor(visa_addr, instr, osc_name)
        failed = self._apply_was_settings_to_oscilloscope(executor, library, model_id, was_data)
        if failed is None:
            return  # the connection broke: already in the report
        if failed:
            self._scope_note("warning", "rc_scope_calls_failed", name=osc_name, count=len(failed))
            for exc in failed[:10]:
                self._scope_report.append(("warning", f"  • {exc}"))
        else:
            self._scope_note("ok", "rc_scope_done", name=osc_name, file=was_file)

    def _configure_serial(self, instr, visa_addr, inst):
        """
        Serial (ASRL) resources: set baud rate, data bits, parity, stop bits and flow control
        on the pyvisa resource before the first command. Values come from the instrument
        library (factory settings of the manual) and can be overridden per instrument by a
        'serial' entry in the project's .inst file. They must match the instrument's own
        front-panel RS-232 settings.
        """
        if not str(visa_addr).upper().startswith('ASRL'):
            return
        library = self.instruments_manager.get_library() if self.instruments_manager else None
        model_key = inst.get('model_id', inst.get('model', ''))
        model_id = library.resolve_model_id(model_key) if library else None
        cfg = dict(library.serial_settings(model_id)) if model_id else {}
        cfg.update(inst.get('serial') or {})
        self.__dict__.setdefault('_serial_cfg', {})[visa_addr] = cfg
        if not cfg:
            return
        from ola.serial_config import apply_serial_settings
        try:
            apply_serial_settings(instr, cfg)
            print(f"[RemoteControlTab] serial {visa_addr}: {cfg}")
        except (ValueError, AttributeError) as exc:
            if self.logger:
                self.logger.error(f"Serial settings for {visa_addr} not applied: {exc}")

    def _get_instrument_executor(self, visa_addr, instr, name, library=None, model_id=None):
        """Executor (ola.instrument.Instrument) of one instrument, one per VISA resource.
        A model that is controlled by a driver (access "driver") gets its driver."""
        from ola._visa import VisaConnection
        from ola.drivers import driver_for
        from ola.instrument import Instrument
        executors = self.__dict__.setdefault('_executors', {})
        entry = executors.get(visa_addr)
        if entry is None or entry[0] is not instr:
            timeout_ms = int(getattr(instr, 'timeout', None) or 5000)
            connection = VisaConnection(instr, visa_addr, timeout_ms, pyvisa)
            cfg = self.__dict__.get('_serial_cfg', {}).get(visa_addr)
            if cfg and ('write_termination' in cfg or 'read_termination' in cfg):
                connection.set_terminators(
                    cfg.get('write_termination', '\n'), cfg.get('read_termination', '\n'))
            driver = driver_for(library, model_id, connection) if library and model_id else None
            entry = (instr, Instrument(name, connection, driver))
            executors[visa_addr] = entry
        return entry[1]

    def _apply_was_settings_to_oscilloscope(self, executor, library, model_id, was_data):
        """Apply the settings of the .was file with logical calls (the same for every brand):
        the planner turns them into the commands of the model, the executor sends them. A call
        the model does not support or refuses (CALL-xxx) is skipped and the others are applied.
        Returns the calls that failed, or None if the instrument did not answer at all (the
        report says why)."""
        from ola.call_errors import CallError, StepFailedError
        from ola.call_planner import plan_call
        from ola.was_calls import oscilloscope_calls_from_was

        failed = []
        name_of = getattr(executor, 'name', '')
        for name, args in oscilloscope_calls_from_was(was_data):
            try:
                executor.run(plan_call(library, model_id, name, args))
                print(f"[RemoteControlTab] {name} {args}")
            except StepFailedError as exc:
                # the instrument did not answer (timeout, connection lost): the other settings
                # would only wait for the same timeout
                self._scope_note("error", "rc_scope_no_answer", name=name_of, error=exc)
                return None
            except CallError as exc:  # a setting the model has not got or does not accept
                failed.append(exc)
                print(f"[RemoteControlTab] {exc}")
                if self.logger:
                    self.logger.error(str(exc))
            except Exception as exc:
                self._scope_note("error", "rc_scope_failed", name=name_of, error=exc)
                return None
        return failed

    @staticmethod
    def _extract_channel_number(ch_ref):
        """Channel number of 'CH1', 'CHAN1', 'C1', '1' (None if absent)."""
        from ola.was_calls import extract_channel_number
        return extract_channel_number(ch_ref)

    def _ensure_visa_initialized(self):
        """
        Inizializza il VISA resource manager solo quando necessario (lazy loading).
        Questo evita segmentation fault durante l'avvio dell'applicazione.
        """
        if self._visa_init_attempted:
            return self.rm is not None

        self._visa_init_attempted = True

        if not PYVISA_AVAILABLE or pyvisa is None:
            print("PyVISA not available")
            return False

        try:
            print("starting the VISA resource manager...")
            # Prova prima con backend sicuro @py
            try:
                self.rm = pyvisa.ResourceManager('@py')
                print("✓ VISA resource manager started with the @py backend")
                return True
            except Exception as e:
                print(f"@py backend failed: {e}")
                # Fallback al backend di default
                try:
                    self.rm = pyvisa.ResourceManager()
                    print("✓ VISA resource manager started with the default backend")
                    return True
                except Exception as e2:
                    print(f"default backend failed: {e2}")

        except Exception as e:
            print(f"✗ starting VISA failed: {e}")

        self.rm = None
        print("instrument control disabled: PyVISA problems")
        return False

    def safe_retry_connection(self, inst, btn, timer_key):
        """
        Background auto-retry for a failed VISA connection.

        Retries are gated on the connect button remaining checked: if the user
        unchecks it while a retry is pending the next call will bail out
        without attempting to connect.  After _MAX_RETRY_ATTEMPTS consecutive
        failures the retry loop stops and the button is left in the failed
        (red/unchecked) state so the user must manually re-initiate.
        """
        try:
            # Verifica se il button è ancora valido
            if btn is None or not hasattr(btn, 'setStyleSheet'):
                # Button was destroyed – clean up and stop retrying.
                if timer_key in self.connection_timers:
                    self.connection_timers[timer_key].stop()
                    self.connection_timers[timer_key].deleteLater()
                    del self.connection_timers[timer_key]
                self.connection_retry_counts.pop(timer_key, None)
                return

            # User opt-in gate: if the button is no longer checked the user
            # has cancelled the auto-retry (by unchecking / reloading the tab).
            if not btn.isChecked():
                if timer_key in self.connection_timers:
                    self.connection_timers[timer_key].stop()
                    self.connection_timers[timer_key].deleteLater()
                    del self.connection_timers[timer_key]
                self.connection_retry_counts.pop(timer_key, None)
                return

            # Prova a connetterti di nuovo
            if not self._ensure_visa_initialized():
                btn.setStyleSheet('border: 2px solid orange;')
                btn.setChecked(False)
                btn.setToolTip(self._t("rc_visa_missing"))
                self.connection_retry_counts.pop(timer_key, None)
                return

            visa_addr = inst.get('visa_address', None)
            if not visa_addr:
                btn.setStyleSheet('border: 2px solid red;')
                btn.setChecked(False)
                self.connection_retry_counts.pop(timer_key, None)
                return

            try:
                existing_instr = self.visa_connections.get(visa_addr)
                if existing_instr is not None:
                    try:
                        existing_instr.close()
                    except Exception as close_error:
                        self.error_handler.handle_visa_error(
                            close_error,
                            f"close existing connection to {visa_addr}",
                            show_dialog=False
                        )
                    self.visa_connections.pop(visa_addr, None)
                instr = self.rm.open_resource(visa_addr)
                self._configure_serial(instr, visa_addr, inst)
                self.visa_connections[visa_addr] = instr
                btn.setStyleSheet('border: 2px solid green;')
                btn.setChecked(True)
                # Connection succeeded – cancel timer and reset retry counter.
                if timer_key in self.connection_timers:
                    timer = self.connection_timers[timer_key]
                    timer.stop()
                    timer.deleteLater()
                    del self.connection_timers[timer_key]
                self.connection_retry_counts.pop(timer_key, None)
            except Exception as e:
                # Log without showing a dialog during background retry attempts.
                self.error_handler.handle_visa_error(e, f"retry connection to {visa_addr}", show_dialog=False)

                attempt = self.connection_retry_counts.get(timer_key, 0) + 1
                self.connection_retry_counts[timer_key] = attempt

                if attempt >= self._MAX_RETRY_ATTEMPTS:
                    # Reached the retry cap – give up and leave the button in the
                    # failed state so the user can decide when to reconnect.
                    btn.setStyleSheet('border: 2px solid red;')
                    btn.setChecked(False)
                    if timer_key in self.connection_timers:
                        try:
                            self.connection_timers[timer_key].stop()
                            self.connection_timers[timer_key].deleteLater()
                            del self.connection_timers[timer_key]
                        except Exception:
                            logger.debug("Failed to clean up connection timer %s", timer_key)
                    self.connection_retry_counts.pop(timer_key, None)
                    return

                # Keep button checked (orange = retrying) so the user can
                # uncheck it to cancel the loop before the next attempt fires.
                btn.setStyleSheet('border: 2px solid orange;')
                btn.setChecked(True)

                # Exponential back-off: 5 s, 10 s, 20 s, 40 s, 60 s (capped).
                delay_ms = min(self._RETRY_BASE_DELAY_MS * (2 ** (attempt - 1)), 60000)

                # Create a fresh single-shot timer for the next retry attempt.
                # (The previous timer already fired and cannot be restarted.)
                if timer_key in self.connection_timers:
                    try:
                        self.connection_timers[timer_key].stop()
                        self.connection_timers[timer_key].deleteLater()
                    except Exception:
                        logger.debug("Failed to stop/delete old timer %s", timer_key)
                new_timer = QTimer(self)
                new_timer.setSingleShot(True)
                new_timer.timeout.connect(lambda: self.safe_retry_connection(inst, btn, timer_key))
                self.connection_timers[timer_key] = new_timer
                new_timer.start(delay_ms)

        except Exception as e:
            # Gestisci qualsiasi errore inaspettato, inclusi crash UI
            try:
                # Usa il sistema di gestione errori centralizzato
                if "wrapped C/C++ object" in str(e) and "has been deleted" in str(e):
                    self.error_handler.handle_ui_error(e, "retry connection timer")
                else:
                    self.error_handler.handle_error(
                        e, "Unexpected error in connection retry", show_dialog=False, code="UI-003")
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Errore in safe_retry_connection: {e}")

            if timer_key in self.connection_timers:
                try:
                    self.connection_timers[timer_key].stop()
                    self.connection_timers[timer_key].deleteLater()
                    del self.connection_timers[timer_key]
                except RuntimeError:
                    pass
            self.connection_retry_counts.pop(timer_key, None)

    def diagnose_connection(self, visa_address: str) -> dict:
        """
        Perform diagnostic tests on instrument connection.

        Delegates to :func:`frontend.core.tools.diagnose_connection` so that
        the pure networking logic lives in the ``core`` layer and is reusable /
        testable independently of this widget.

        Args:
            visa_address: VISA address to diagnose (e.g.,
                'TCPIP0::192.168.1.100::inst0::INSTR')

        Returns:
            Dictionary with diagnostic results
        """
        from frontend.core.tools import diagnose_connection as _diagnose
        return _diagnose(visa_address, translate=self._t)

    def show_connection_diagnostics(self, visa_address: str):
        """
        Show connection diagnostics dialog with detailed troubleshooting information.
        Diagnostics are run in a background thread to avoid blocking the UI.

        Args:
            visa_address: VISA address to diagnose
        """
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QProgressBar
        from PyQt6.QtCore import QThread, pyqtSignal as Signal, QObject

        dialog = QDialog(self)
        dialog.setWindowTitle(f"{self._t('rc_diagnostics_title')} - {visa_address}")
        dialog.setMinimumSize(600, 400)

        layout = QVBoxLayout(dialog)

        # Progress bar
        progress = QProgressBar()
        progress.setRange(0, 0)  # Indeterminate
        layout.addWidget(progress)

        # Text area for results
        text_area = QTextEdit()
        text_area.setReadOnly(True)
        layout.addWidget(text_area)

        # Close button
        close_btn = QPushButton(self._t("close"))
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn)

        dialog.show()

        # Worker that runs blocking diagnostics in a background thread
        class _DiagnosticsWorker(QObject):
            finished = Signal(dict)

            def __init__(self, parent_tab, addr):
                super().__init__()
                self._tab = parent_tab
                self._addr = addr

            def run(self):
                try:
                    results = self._tab.diagnose_connection(self._addr)
                except Exception as e:
                    results = {
                        'visa_address': self._addr,
                        'address_valid': False,
                        'host_reachable': False,
                        'port_open': False,
                        'visa_available': PYVISA_AVAILABLE,
                        'recommendations': [self._tab._t("rc_diag_failed", error=e)],
                    }
                self.finished.emit(results)

        def on_results(results):
            # Guard against the dialog being closed before the worker finished.
            # Accessing destroyed Qt C++ widgets raises RuntimeError; catch it
            # and bail out silently — the user already dismissed the dialog.
            try:
                progress.setVisible(False)
                # Format results
                t = self._t
                yes_no = lambda ok: t("rc_diag_yes") if ok else t("rc_diag_no")  # noqa: E731
                mark = lambda ok: "✓" if ok else "✗"  # noqa: E731
                output = t("rc_diag_header", address=visa_address) + "\n"
                output += "=" * 60 + "\n\n"
                visa_ok, valid = results['visa_available'], results['address_valid']
                output += f"✓ {t('rc_diag_visa')}: {yes_no(visa_ok)}\n"
                output += f"{mark(valid)} {t('rc_diag_address_valid')}: {yes_no(valid)}\n"
                if 'host' in results:
                    output += f"\n{t('rc_diag_host')}: {results['host']}\n"
                    output += f"{t('rc_diag_port')}: {results['port']}\n"
                    if 'resolved_addresses' in results:
                        output += f"{t('rc_diag_resolved')}: {', '.join(results['resolved_addresses'])}\n"
                    output += "\n"
                    for label, ok in (
                        ('rc_diag_dns', results.get('host_resolves')),
                        ('rc_diag_reachable', results['host_reachable']),
                        ('rc_diag_port_open', results['port_open']),
                    ):
                        output += f"{mark(ok)} {t(label)}: {yes_no(ok)}\n"
                if results['recommendations']:
                    output += "\n" + "=" * 60 + "\n"
                    output += t("rc_diag_recommendations") + ":\n"
                    output += "=" * 60 + "\n\n"
                    for i, rec in enumerate(results['recommendations'], 1):
                        output += f"{i}. {rec}\n\n"
                text_area.setText(output)
            except RuntimeError:
                # Dialog was closed before results arrived; widgets are gone.
                return
            # Log diagnostics
            if self.logger:
                self.logger.info(f"Connection diagnostics completed for {visa_address}")
                self.logger.debug(f"Diagnostics results: {results}")
            # Signal-based cleanup: ask the thread to stop; deleteLater when it finishes
            thread.quit()

        # Parent the thread to the dialog so it is cleaned up when the dialog
        # is destroyed.  When the user closes the dialog, dialog.finished ->
        # thread.quit() exits the thread's event loop *after* worker.run()
        # returns (thread.quit() cannot interrupt a running synchronous call).
        # on_results() is therefore guarded with a try/except RuntimeError so
        # that any attempt to touch already-destroyed dialog widgets is
        # silently ignored if the results arrive after the dialog is closed.
        thread = QThread(dialog)
        worker = _DiagnosticsWorker(self, visa_address)
        # Keep strong references on dialog so neither object is
        # garbage-collected while the background diagnostics are still running.
        dialog._diagnostics_thread = thread
        dialog._diagnostics_worker = worker

        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(on_results)

        def _cleanup_diagnostics_refs():
            # Drop strong references once the thread has finished so the
            # dialog doesn't hold onto them indefinitely, and schedule the
            # thread object for deletion.
            dialog._diagnostics_worker = None
            dialog._diagnostics_thread = None
            thread.deleteLater()

        # Clean up worker/thread without blocking the GUI thread
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(_cleanup_diagnostics_refs)
        # Exit the thread event loop once the dialog is closed (worker.run()
        # may still be running; it will finish naturally and on_results will
        # handle the destroyed-widget case via RuntimeError guard).
        dialog.finished.connect(thread.quit)
        thread.start()

    def _show_connection_error_with_diagnostics(self, error_message, visa_address):
        """
        Show connection error with option to run diagnostics.

        Args:
            error_message: The error message to display
            visa_address: The VISA address that failed to connect
        """
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit

        dialog = QDialog(self)
        dialog.setWindowTitle(self._t("rc_connection_error"))
        dialog.setMinimumWidth(500)

        layout = QVBoxLayout()

        # Error icon and title
        title_layout = QHBoxLayout()
        title_label = QLabel("❌ " + self._t("rc_connection_failed"))
        set_class(title_label, "error")
        title_label.setStyleSheet("font-size: 14pt; font-weight: bold;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        layout.addLayout(title_layout)

        # Error message
        error_text = QTextEdit()
        error_text.setReadOnly(True)
        error_text.setPlainText(error_message)
        error_text.setMaximumHeight(200)
        layout.addWidget(error_text)

        # Buttons
        button_layout = QHBoxLayout()

        diagnose_btn = QPushButton("🔍 " + self._t("rc_run_diagnostics"))
        diagnose_btn.clicked.connect(lambda: [dialog.accept(), self.show_connection_diagnostics(visa_address)])
        diagnose_btn.setStyleSheet("background-color: #1976d2; color: white; padding: 8px;")

        close_btn = QPushButton(self._t("close"))
        close_btn.clicked.connect(dialog.reject)
        close_btn.setStyleSheet("padding: 8px;")

        button_layout.addStretch()
        button_layout.addWidget(diagnose_btn)
        button_layout.addWidget(close_btn)

        layout.addLayout(button_layout)
        dialog.setLayout(layout)

        # Log error
        if self.logger:
            self.logger.error(f"Connection error for {visa_address}: {error_message}")

        dialog.exec()

    def _retranslate(self):
        """Set every fixed text of the tab (title, tooltips, measurements box and its controls)
        in the language of the application; without a translator, in English."""
        self.label.setText(self._t('remote_control'))
        self.osc_btn.setToolTip(self._t('rc_osc_tip'))
        self.reload_btn.setToolTip(self._t('rc_reload_tip'))
        self.meas_group.setTitle(self._t('measurements'))
        # the controls of the measurements box exist only when the file has meters
        for name, key in (('refresh_btn', 'rc_refresh'), ('auto_refresh_cb', 'rc_auto_refresh'),
                          ('interval_label', 'rc_interval')):
            widget = getattr(self, name, None)
            if widget is not None:
                try:
                    widget.setText(self._t(key))
                except RuntimeError:  # the widget was deleted with the old measurements box
                    setattr(self, name, None)

    def update_translation(self, translator):
        """
        Update UI elements with translated text.
        :param translator: Translator instance for language translation.
        """
        self.translator = translator
        self._retranslate()
        # Optionally update channel group titles
        for group in self.current_channel_widgets:
            inst = group.property('instrument')
            ch = group.property('channel')
            if inst and ch:
                group.setTitle(self._format_channel_title(inst, ch))
            banner_label = group.property('manual_mode_banner_label')
            if banner_label is not None:
                try:
                    banner_label.setText(f"{self._MANUAL_ICON} {self._t('manual_instrument_label')}")
                except RuntimeError:
                    pass  # widget was destroyed

    def load_instruments(self, inst_file_path):
        """
        Load instruments from the specified .inst file and create corresponding UI controls.
        :param inst_file_path: Path to the .inst file to load.
        """
        msg = f"load_instruments called with path: {inst_file_path}"
        print(msg)
        if self.logger:
            self.logger.info(msg)

        try:
            # Clear previous controls - pulisci colonne
            self._instrument_items = []
            for i in reversed(range(self.left_column.count())):
                item = self.left_column.itemAt(i)
                if item:
                    widget = item.widget()
                    if widget:
                        widget.setParent(None)

            for i in reversed(range(self.right_column.count())):
                item = self.right_column.itemAt(i)
                if item:
                    widget = item.widget()
                    if widget:
                        widget.setParent(None)

            self.current_channel_widgets.clear()

            # Clear measurement area
            for i in reversed(range(self.meas_layout.count())):
                item = self.meas_layout.itemAt(i)
                if item:
                    widget = item.widget()
                    if widget:
                        if hasattr(widget, 'stop_reading'):  # a panel reading continuously
                            widget.stop_reading()
                        widget.setParent(None)

            # Stop measurement timer if exists
            if hasattr(self, 'measurement_timer'):
                self.measurement_timer.stop()

            for timer_key, timer in self.connection_timers.items():
                try:
                    timer.stop()
                    timer.deleteLater()
                except RuntimeError:
                    pass
            self.connection_timers.clear()
            self.connection_retry_counts.clear()

            self.meas_labels.clear()
            # a reloaded file is sent again to the meters (the instrument may have been reset)
            self.__dict__.pop('_datalogger_signature', None)
            self.__dict__.pop('_multimeter_signature', None)
            # Close previous VISA connections
            for inst in self.visa_connections.values():
                try:
                    inst.close()
                except Exception:
                    logger.debug("Failed to close VISA connection during refresh")
            self.visa_connections = {}
            if not inst_file_path or not os.path.isfile(inst_file_path):
                return

            with open(inst_file_path, 'r', encoding='utf-8') as f:
                inst_data = json.load(f)

            # DEBUG: Stampa tutti gli strumenti caricati
            print(f"\n=== DEBUG: instruments loaded from {inst_file_path} ===")
            for idx, inst in enumerate(inst_data.get('instruments', [])):
                print(f"  [{idx}] {inst.get('instance_name', 'N/A')} - type: {inst.get('instrument_type', 'N/A')}")
                print(f"       channels: {len(inst.get('channels', []))}")
                for ch_idx, ch in enumerate(inst.get('channels', [])):
                    print(f"         [{ch_idx}] {ch.get('name', 'N/A')} - Enabled: {ch.get('enabled', False)}")
            print("=" * 50 + "\n")

            # --- First, collect all datalogger/multimeter channels for measurement area ---
            # Note: Oscilloscopes are excluded as they cannot perform continuous automatic measurements
            self.meas_vars = []  # [(inst, ch)]
            for inst in inst_data.get('instruments', []):
                inst_type = inst.get('instrument_type', '')
                # Gestisce varianti di naming: datalogger/dataloggers, multimeter/multimeters
                if inst_type in ['multimeter', 'multimeters']:
                    # one input: the first enabled channel is the one measured
                    ch = measured_channel(inst.get('channels', []))
                    if ch is not None:
                        self.meas_vars.append((inst, ch))
                elif inst_type in ['datalogger', 'dataloggers']:
                    for ch in inst.get('channels', []):
                        is_enabled = ch.get('enabled', True)  # Solo canali abilitati
                        if is_enabled:
                            self.meas_vars.append((inst, ch))
                            print(f"    → measurement channel added: {inst.get('instance_name', 'N/A')} - {ch.get('name', 'N/A')}")

            if self.meas_vars:
                # Crea un layout a griglia per le misure
                # The measurements flow: as many per line as the width allows (a grid of four made
                # the box wider than a half-screen window)
                meas_grid = FlowLayout(spacing=6)

                for inst, ch in self.meas_vars:
                    # meas_vars only contains datalogger/multimeter channels
                    var_name = ch.get('measured_variable', ch.get('name', 'Unknown'))
                    inst_type = inst.get('instrument_type', '')
                    if inst_type in ['multimeter', 'multimeters', 'datalogger', 'dataloggers']:
                        unit = ch.get('unit', 'V')  # Campo 'unit' nel file .inst
                    else:
                        unit = ch.get('unit_of_measure', 'V')  # Default per altri strumenti

                    # Crea etichetta con formato: Nome_variabile = --- unità
                    label = QLabel(f"{var_name} = --- {unit}")
                    label.setProperty("class", "measurement")
                    label.setStyleSheet("""
                        QLabel {
                            border: 2px solid #45475a;
                            padding: 8px;
                            margin: 2px;
                            border-radius: 6px;
                            font-family: 'Courier New', monospace;
                            font-size: 12px;
                            min-width: 150px;
                            font-weight: 600;
                        }
                    """)

                    meas_grid.addWidget(label)
                    self.meas_labels[(inst.get('instance_name',''), var_name)] = label

                # Crea un widget contenitore per la griglia
                meas_widget = QWidget()
                meas_widget.setLayout(meas_grid)
                self.meas_layout.addWidget(meas_widget)

                # Add control buttons in horizontal layout
                control_layout = FlowLayout(spacing=6)  # the controls wrap when the window is narrow

                refresh_btn = QPushButton()
                self.refresh_btn = refresh_btn
                refresh_btn.clicked.connect(self.refresh_measurements_manual)
                control_layout.addWidget(refresh_btn)

                # Toggle per aggiornamento automatico
                self.auto_refresh_cb = QCheckBox()
                self.auto_refresh_cb.setChecked(True)
                self.auto_refresh_cb.toggled.connect(self.toggle_auto_refresh)
                control_layout.addWidget(self.auto_refresh_cb)

                # Slider per intervallo di aggiornamento
                interval_label = QLabel()
                self.interval_label = interval_label
                control_layout.addWidget(interval_label)

                self.interval_slider = QSlider(Qt.Orientation.Horizontal)
                self.interval_slider.setRange(1, 10)  # 1-10 secondi
                self.interval_slider.setValue(2)  # Default 2 secondi
                self.interval_slider.valueChanged.connect(self.update_refresh_interval)
                control_layout.addWidget(self.interval_slider)

                self.interval_value_label = QLabel('2s')
                control_layout.addWidget(self.interval_value_label)


                control_widget = QWidget()
                control_widget.setLayout(control_layout)
                self.meas_layout.addWidget(control_widget)
                self._retranslate()  # the three new controls get their texts

                # Setup timer per aggiornamento automatico
                self.measurement_timer = QTimer()
                self.measurement_timer.timeout.connect(self.refresh_measurements_auto)
                if self.auto_refresh_cb.isChecked():
                    self.measurement_timer.start(2000)  # Start con 2 secondi

            # --- Analizza la struttura degli strumenti per ottimizzare il layout ---
            power_instruments = []
            total_enabled_channels = 0

            for inst in inst_data.get('instruments', []):
                inst_type = inst.get('instrument_type', '')
                if inst_type in ['power_supply', 'power_supplies', 'electronic_load', 'electronic_loads']:
                    enabled_channels = [ch for ch in inst.get('channels', []) if ch.get('enabled', False)]
                    if enabled_channels:
                        power_instruments.append({
                            'inst': inst,
                            'enabled_channels': enabled_channels,
                            'channel_count': len(enabled_channels)
                        })
                        total_enabled_channels += len(enabled_channels)
                elif inst_type in ['function_generator', 'function_generators']:
                    controls = self._function_generator_controls(inst)
                    power_instruments.append({
                        'inst': inst,
                        'enabled_channels': [],
                        'channel_count': controls.channels,
                        'panel': controls,
                    })
                    total_enabled_channels += controls.channels
                elif inst_type in ['rf_signal_generator', 'rf_signal_generators']:
                    power_instruments.append({
                        'inst': inst,
                        'enabled_channels': [],
                        'channel_count': 1,
                        'panel': self._rf_generator_controls(inst),
                        'panel_kind': 'rf',
                    })
                    total_enabled_channels += 1

            print("\n=== DEBUG: instruments for the layout ===")
            print(f"valid instruments: {len(power_instruments)}")
            print(f"enabled channels: {total_enabled_channels}")

            # Ordina gli strumenti dal più grande al più piccolo per un miglior bilanciamento
            power_instruments.sort(key=lambda x: x['channel_count'], reverse=True)

            for i, inst_info in enumerate(power_instruments):
                inst_name = inst_info['inst'].get('instance_name', 'N/A')
                channel_count = inst_info['channel_count']
                print(f"  -> instrument [{i}]: {inst_name} ({channel_count} channels)")

            print(f"layout: {total_enabled_channels} channels, the columns follow the width")

            # --- Then, for each power supply/electronic load, create a group per instrument ---
            print("\n=== DEBUG: controls of supplies and loads ===")
            # Azzera le colonne prima di aggiungere nuovi widget
            for col in (self.left_column, self.right_column):
                while col.count():
                    item = col.takeAt(0)
                    widget = item.widget()
                    if widget:
                        widget.setParent(None)
            self._instrument_items = []

            for inst_info in power_instruments:
                inst = inst_info['inst']
                enabled_channels = inst_info['enabled_channels']
                channel_count = inst_info['channel_count']

                print(f"instrument: {inst.get('instance_name', 'N/A')} - {channel_count} channels")

                # --- Pulsante di connessione per strumento ---
                conn_btn = QPushButton(self._t("rc_connect", name=inst.get('instance_name', '')))
                conn_btn.setCheckable(True)
                conn_btn.setStyleSheet('QPushButton { font-weight: bold; padding: 5px; }')
                # Manual instruments have no remote/VISA control: hide the connect button
                # and skip all connection/retry logic for them.
                if inst.get('is_manual', False):
                    conn_btn.setVisible(False)
                def try_connect(inst, btn):
                    # Manual instruments have no VISA control – bail out immediately.
                    if inst.get('is_manual', False):
                        return
                    visa_addr = inst.get('visa_address', '')
                    if not visa_addr:
                        btn.setStyleSheet('border: 2px solid orange;')
                        btn.setChecked(False)
                        return
                    # Compute timer_key once so it is available in both success and failure paths
                    timer_key = f"{inst.get('instance_name', 'unknown')}_{id(btn)}"
                    try:
                        if not self._ensure_visa_initialized():
                            btn.setStyleSheet('border: 2px solid red;')
                            btn.setChecked(False)
                            return
                        # Close any existing connection for this address before opening a new one
                        previous_instr = self.visa_connections.get(visa_addr)
                        if previous_instr is not None:
                            try:
                                previous_instr.close()
                            except Exception as close_error:
                                self.error_handler.handle_visa_error(
                                    close_error,
                                    f"close existing connection to {visa_addr}",
                                    show_dialog=False
                                )
                            self.visa_connections.pop(visa_addr, None)
                        instr = self.rm.open_resource(visa_addr)
                        self._configure_serial(instr, visa_addr, inst)
                        self.visa_connections[visa_addr] = instr
                        btn.setStyleSheet('border: 2px solid green;')
                        btn.setChecked(True)
                        # Cancel any pending retry timer for this instrument on successful connect
                        if timer_key in self.connection_timers:
                            self.connection_timers[timer_key].stop()
                            self.connection_timers[timer_key].deleteLater()
                            del self.connection_timers[timer_key]
                        # Clear retry history so a future re-connect starts with a fresh counter
                        self.connection_retry_counts.pop(timer_key, None)
                    except Exception as e:
                        btn.setStyleSheet('border: 2px solid red;')
                        btn.setChecked(False)

                        # Determine whether this is a connection-refused or timeout VISA error
                        # to decide whether to show the diagnostics dialog.
                        # Prefer checking e.error_code (stable API) with string matching as fallback.
                        err_str = str(e).lower()
                        _is_visa_io = (
                            PYVISA_AVAILABLE
                            and isinstance(e, pyvisa.errors.VisaIOError)
                        )

                        def _visa_refused(exc, es):
                            if hasattr(exc, 'error_code') and hasattr(pyvisa, 'constants'):
                                try:
                                    sc = pyvisa.constants.StatusCode
                                    refused_codes = {
                                        getattr(sc, 'error_resource_not_found', None),
                                        getattr(sc, 'error_connection_lost', None),
                                    }
                                    if exc.error_code in refused_codes - {None}:
                                        return True
                                except Exception:
                                    logger.debug("Failed to check VISA refused error code")
                            return ("can't connect" in es or "connection refused" in es
                                    or "vi_error_rsrc_nfound" in es)

                        def _visa_timeout(exc, es):
                            if hasattr(exc, 'error_code') and hasattr(pyvisa, 'constants'):
                                try:
                                    sc = pyvisa.constants.StatusCode
                                    timeout_code = getattr(sc, 'error_timeout', None)
                                    if timeout_code is not None and exc.error_code == timeout_code:
                                        return True
                                except Exception:
                                    logger.debug("Failed to check VISA timeout error code")
                            return "timeout" in es

                        is_visa_refused = _is_visa_io and _visa_refused(e, err_str)
                        is_visa_timeout = _is_visa_io and _visa_timeout(e, err_str)

                        if is_visa_refused:
                            error_msg = with_code(self._t(
                                "rc_conn_refused", address=visa_addr, error=e), "VISA-001")
                            if self.logger:
                                self.logger.error(f"[VISA-001] {visa_addr}: {e}")
                            self._show_connection_error_with_diagnostics(error_msg, visa_addr)
                        elif is_visa_timeout:
                            show_problem(
                                self, self._t("rc_connection_error"),
                                self._t("rc_conn_timeout", address=visa_addr, error=e),
                                code="VISA-004", exception=e)
                        else:
                            show_problem(
                                self, self._t("rc_connection_error"),
                                self._t("rc_conn_failed", address=visa_addr,
                                        type=type(e).__name__, error=e),
                                code="VISA-003", exception=e)

                        # Safe timer management – schedule a retry regardless of error type.
                        # Keep the button checked (orange) to signal "retrying in progress";
                        # the user can uncheck it to cancel future auto-retries.
                        btn.setStyleSheet('border: 2px solid orange;')
                        btn.setChecked(True)
                        # Reset the retry counter for this instrument so the backoff starts fresh.
                        self.connection_retry_counts.pop(timer_key, None)
                        if timer_key in self.connection_timers:
                            self.connection_timers[timer_key].stop()
                            self.connection_timers[timer_key].deleteLater()

                        timer = QTimer(self)
                        timer.setSingleShot(True)
                        timer.timeout.connect(lambda: self.safe_retry_connection(inst, btn, timer_key))
                        self.connection_timers[timer_key] = timer
                        timer.start(self._RETRY_BASE_DELAY_MS)

                def handle_connect_clicked(checked, i=inst, b=conn_btn):
                    """
                    Handle connect-button clicks with full checked-state awareness.

                    checked=True  → attempt VISA connection (delegates to try_connect).
                    checked=False → user-initiated disconnect: cancel any pending retry
                                    timer, clear the retry counter, and close the existing
                                    VISA connection so resources are released immediately.
                    """
                    t_key = f"{i.get('instance_name', 'unknown')}_{id(b)}"
                    if not checked:
                        # Cancel pending retry timer
                        timer = self.connection_timers.pop(t_key, None)
                        if timer is not None:
                            timer.stop()
                            timer.deleteLater()
                        # Clear retry history so re-connecting starts with a fresh counter
                        self.connection_retry_counts.pop(t_key, None)
                        # Close the VISA connection if one is open
                        v_addr = (
                            i.get('visa_address')
                            or i.get('resource_name')
                            or i.get('resource')
                            or i.get('address')
                        )
                        if v_addr and v_addr in self.visa_connections:
                            try:
                                self.visa_connections[v_addr].close()
                            except Exception as close_err:
                                self.error_handler.handle_visa_error(
                                    close_err,
                                    f"close connection to {v_addr} on user disconnect",
                                    show_dialog=False
                                )
                            self.visa_connections.pop(v_addr, None)
                        b.setStyleSheet('')
                        return
                    # checked=True → attempt connection
                    try_connect(i, b)

                conn_btn.clicked.connect(handle_connect_clicked)

                if inst_info.get('panel') is not None:  # a generator: its own panel
                    inst_group = QGroupBox(self._instrument_title(inst))
                    inst_vbox = QVBoxLayout()
                    inst_vbox.addWidget(conn_btn)
                    if inst_info.get('panel_kind') == 'rf':
                        from frontend.ui.RfGeneratorPanel import RfGeneratorPanel
                        panel = RfGeneratorPanel(
                            inst_info['panel'],
                            lambda call, i=inst, **args: self.run_call(i, None, call, **args),
                            self._t,
                        )
                    else:
                        from frontend.ui.FunctionGeneratorPanel import FunctionGeneratorPanel
                        panel = FunctionGeneratorPanel(
                            inst_info['panel'],
                            lambda number, call, i=inst, **args: self.run_call(
                                i, None, call, channel_number=number, **args),
                            self._t,
                        )
                    inst_vbox.addWidget(panel)
                    inst_group.setLayout(inst_vbox)
                    self._instrument_items.append((inst_group, channel_count))
                    continue

                # Strategia di layout per strumento con molti canali (>3)
                if channel_count > 3:
                    # Crea sotto-colonne per questo strumento
                    print(f"  → instrument with {channel_count} channels: sub-columns")
                    inst_main_group = QGroupBox(self._instrument_title(inst))
                    inst_main_layout = QVBoxLayout()
                    inst_main_layout.addWidget(conn_btn)

                    # Layout orizzontale per le sotto-colonne
                    inst_sub_layout = QHBoxLayout()
                    left_sub_column = QVBoxLayout()
                    right_sub_column = QVBoxLayout()

                    # Distribuisci i canali nelle sotto-colonne
                    for ch_idx, ch in enumerate(enabled_channels):
                        channel_widget = self._create_channel_widget(inst, ch)
                        if ch_idx % 2 == 0:
                            left_sub_column.addWidget(channel_widget)
                        else:
                            right_sub_column.addWidget(channel_widget)
                        self.current_channel_widgets.append(channel_widget)

                    # Aggiungi stretch per allineare in alto
                    left_sub_column.addStretch()
                    right_sub_column.addStretch()

                    # Crea widget contenitori per le sotto-colonne
                    left_sub_widget = QWidget()
                    left_sub_widget.setLayout(left_sub_column)
                    right_sub_widget = QWidget()
                    right_sub_widget.setLayout(right_sub_column)

                    inst_sub_layout.addWidget(left_sub_widget)
                    inst_sub_layout.addWidget(right_sub_widget)

                    inst_main_layout.addLayout(inst_sub_layout)
                    inst_main_group.setLayout(inst_main_layout)

                    self._instrument_items.append((inst_main_group, channel_count))
                    print("  ✓ instrument with sub-columns added")

                else:
                    # Strumento normale: crea groupbox standard
                    inst_group = QGroupBox(self._instrument_title(inst))
                    inst_vbox = QVBoxLayout()
                    inst_vbox.addWidget(conn_btn)

                    # Aggiungi tutti i canali abilitati
                    for ch in enabled_channels:
                        channel_widget = self._create_channel_widget(inst, ch)
                        inst_vbox.addWidget(channel_widget)
                        self.current_channel_widgets.append(channel_widget)

                    inst_group.setLayout(inst_vbox)

                    self._instrument_items.append((inst_group, channel_count))
                    print("  ✓ instrument added")

            print("\n=== final layout ===")
            print(f"channel widgets created: {len(self.current_channel_widgets)}")
            print("=" * 50 + "\n")

            self._arrange_instruments()  # the columns, with a stretch at the top of each

            # Network analyzers: their own panel, reached like the measurements do (a LiteVNA
            # is a driver, not a VISA resource)
            self._add_vna_panels(inst_data.get('instruments', []), inst_file_path)

        except Exception as e:
            error_msg = f"ERROR in load_instruments: {str(e)}\nTraceback: {traceback.format_exc()}"
            print(error_msg)
            if self.logger:
                self.logger.error(error_msg)
            # Error already logged - no popup needed

    def _function_generator_controls(self, inst):
        """What the panel of a function generator shows (ola.control_panels): only the calls its
        model defines in the library; nothing if the model is not in the library."""
        from ola.control_panels import FunctionGeneratorControls, function_generator_controls
        library = self.instruments_manager.get_library() if self.instruments_manager else None
        model_key = inst.get('model_id', inst.get('model', ''))
        model_id = library.resolve_model_id(model_key) if library else None
        if not model_id:
            return FunctionGeneratorControls()
        return function_generator_controls(library, model_id)

    def _rf_generator_controls(self, inst):
        """What the panel of an RF signal generator shows (ola.rf_controls): only the calls its
        model defines in the library; nothing if the model is not in the library."""
        from ola.rf_controls import RfControls, rf_controls
        library = self.instruments_manager.get_library() if self.instruments_manager else None
        model_key = inst.get('model_id', inst.get('model', ''))
        model_id = library.resolve_model_id(model_key) if library else None
        if not model_id:
            return RfControls()
        return rf_controls(library, model_id)

    @staticmethod
    def _instrument_title(inst):
        """Name of an instrument with its model in brackets; just the name when there is no model
        (a manual instrument has none), never empty brackets."""
        name = str(inst.get('instance_name', '') or '').strip()
        model = str(inst.get('model', '') or '').strip()
        if name and model:
            return f"{name} ({model})"
        return name or model

    def _format_channel_title(self, inst, ch):
        """Build the channel group box title, including the manual-instrument badge when applicable."""
        title = f"{inst.get('instance_name', '')} - {ch.get('name', '')}"
        if inst.get('is_manual', False):
            title += f" {self._MANUAL_ICON} [{self._t('manual_instrument')}]"
        return title

    def _t(self, key, **kwargs):
        """Helper to get a translated string, with optional format substitution."""
        if not self.translator or not hasattr(self.translator, 't'):
            from frontend.core.Translator import Translator
            self.translator = Translator()  # English until the application gives its own
        text = self.translator.t(key)
        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, ValueError) as e:
                print(f"[RemoteControlTab] Translation format error for key '{key}': {e}")
                text = f"{key} [format error]"
        return text

    def _close_vna_connector(self):
        connector = getattr(self, '_vna_connector', None)
        if connector is not None:
            try:
                connector.close()
            except Exception as exc:
                logger.debug("closing the VNA connections failed: %s", exc)
        self._vna_connector = None

    # ---- columns of the instruments ----------------------------------------------------------
    COLUMN_GAP = 24  # room between the two columns and at their edges, beside the widest instrument

    def eventFilter(self, watched, event):
        """The columns follow the width of the window: a narrow window has one column to scroll
        down, not two to scroll sideways."""
        if (watched is getattr(self, '_scroll', None).viewport()
                and event.type() == QEvent.Type.Resize and self._instrument_items):
            self._arrange_instruments()
        return super().eventFilter(watched, event)

    def _two_columns_width(self) -> int:
        """The least width of the window for two columns: the widest instrument twice, and the gap."""
        widest = max((w.sizeHint().width() for w, _ in self._instrument_items), default=0)
        return 2 * widest + self.COLUMN_GAP + self.channels_layout.spacing()

    def _arrange_instruments(self, width=None) -> int:
        """Put the instruments in one column, or in two (balanced by their channels) when the window
        is wide enough for two. The widgets are moved, not rebuilt. Returns the number of columns."""
        for column in (self.left_column, self.right_column):
            while column.count():
                column.takeAt(0)  # the stretch goes too; the widgets are placed again below
        if width is None:
            width = self._scroll.viewport().width()
        items = self._instrument_items
        count = 2 if len(items) > 1 and width >= self._two_columns_width() else 1
        columns = [self.left_column, self.right_column][:count]
        loads = [0] * count
        for widget, channels in items:
            index = loads.index(min(loads))  # the column with fewer channels
            columns[index].addWidget(widget)
            loads[index] += channels
        for column in columns:
            column.addStretch()
        self._column_count = count
        return count

    def _add_vna_panels(self, instruments, inst_file_path):
        """One VnaPanel (sweep, traces, plot, export) per network analyzer of the file, in the
        measurements area. The connection is the one of the measurements
        (ola.connection.ProjectConnector), so drivers such as the LiteVNA work too."""
        from pathlib import Path
        from frontend.ui.VnaPanel import VnaPanel
        from ola.connection import ProjectConnector
        from ola.vna_controls import VnaControls, vna_controls
        self._close_vna_connector()
        analyzers = [i for i in instruments
                     if str(i.get('instrument_type', '')).lower() in ('network_analyzer', 'vna')]
        if not analyzers:
            return
        library = self.instruments_manager.get_library() if self.instruments_manager else None
        if library is None:
            return
        path = Path(inst_file_path)
        self._vna_connector = ProjectConnector(library, lambda p=path: p)
        for inst in analyzers:
            model_id = library.resolve_model_id(inst.get('model_id', inst.get('model', '')))
            controls = vna_controls(library, model_id) if model_id else VnaControls()
            name = inst.get('instance_name', '')
            panel = VnaPanel(
                self._instrument_title(inst),
                controls,
                lambda n=name: self._vna_connector.connect(n),
                self._t,
            )
            self.meas_layout.addWidget(panel)

    def _load_controls(self, inst):
        """What the panel of an electronic load shows (ola.load_controls): only the calls its
        model defines in the library; nothing if the model is not in the library."""
        from ola.load_controls import LoadControls, load_controls
        library = self.instruments_manager.get_library() if self.instruments_manager else None
        model_key = inst.get('model_id', inst.get('model', ''))
        model_id = library.resolve_model_id(model_key) if library else None
        if not model_id:
            return LoadControls()
        return load_controls(library, model_id)

    @staticmethod
    def _is_load(inst):
        """True for an electronic load (its calls are load_on, set_current_level, ...)."""
        return str(inst.get('instrument_type', '')).lower() in ('electronic_load', 'electronic_loads')

    def _setpoint_call(self, inst, quantity):
        """Logical call that sets the voltage or the current of a supply or an electronic load."""
        if self._is_load(inst):
            return 'set_voltage_level' if quantity == 'voltage' else 'set_current_level'
        return 'set_voltage' if quantity == 'voltage' else 'set_current'

    def _output_call(self, inst, on):
        """Logical call that switches the output of a supply or the input of a load."""
        if self._is_load(inst):
            return 'load_on' if on else 'load_off'
        return 'output_on' if on else 'output_off'

    def _report_call_error(self, exc):
        """Tell the operator that a command or a reading did not happen: a box with the code
        (ERROR_CODES.md) and the reason, and the log. A not connected instrument, an instrument
        that does not answer, and any other failure all come here."""
        print(f"ERROR: {exc}")
        if isinstance(exc, StepFailedError):
            text = self._t("rc_no_answer")
        else:
            text = str(exc)
        cause = getattr(exc, "cause", None)
        if cause is not None:
            text = f"{text}\n\n{self._t('err_details')}: {cause}"
        show_problem(self, self._t("rc_command_failed"), text, exception=exc)

    def _connected(self, inst, call=None):
        """The VISA instrument of an entry, ready for a command. When it cannot be reached the
        command is not sent: ``InstrumentNotConnectedError`` says why (no address, VISA not
        installed, the address does not answer, not connected)."""
        name = inst.get('instance_name', 'N/A')
        address = inst.get('visa_address', '')
        if not address:
            raise InstrumentNotConnectedError(
                self._t("rc_no_address", name=name), call=call, code="INST-005")
        if not self._ensure_visa_initialized():
            raise InstrumentNotConnectedError(
                self._t("rc_visa_unavailable", name=name), call=call, code="VISA-005")
        instr = self.get_visa_instrument(inst)
        if instr is None:
            cause = self.__dict__.get('_open_error')
            raise InstrumentNotConnectedError(
                self._t("rc_not_connected", name=name, address=address), call=call,
                code="VISA-002" if cause is not None else "INST-006", cause=cause)
        return instr

    def _manual_prompt(self, request):
        """Ask the operator to carry out a manual action: True after OK, False on Cancel."""
        message = self._t(request.key, instrument=request.instrument, **request.args)
        if message == request.key:  # no translation for this call: use the English sentence
            message = request.text
        return self._show_manual_prompt(message)

    def _show_manual_prompt(self, message):
        """
        Show a popup for a manual instrument action.
        Returns True if the user confirmed (OK), False if cancelled.
        """
        from PyQt6.QtWidgets import QMessageBox
        title = self._t('manual_instrument_title')
        reply = QMessageBox.question(
            self,
            title,
            message,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Ok
        )
        return reply == QMessageBox.StandardButton.Ok

    def _create_channel_widget(self, inst, ch):
        """
        Crea un widget per un singolo canale di strumento.
        :param inst: Dati dello strumento
        :param ch: Dati del canale
        :return: QGroupBox contenente i controlli del canale
        """
        print(f"      → controls of channel {ch.get('name', 'N/A')}")
        is_manual = inst.get('is_manual', False)
        if self._is_load(inst) and not is_manual:  # a library load: modes, readings, protections
            from frontend.ui.ElectronicLoadPanel import ElectronicLoadPanel
            panel = ElectronicLoadPanel(
                self._format_channel_title(inst, ch),
                self._load_controls(inst),
                ch,
                lambda call, i=inst, **args: self.run_call(i, None, call, **args),
                self._t,
            )
            panel.setProperty('instrument', inst)
            panel.setProperty('channel', ch)
            panel.setProperty('manual_mode_banner_label', None)
            return panel
        group_title = self._format_channel_title(inst, ch)
        group = QGroupBox(group_title)
        group.setProperty('instrument', inst)
        group.setProperty('channel', ch)
        group.setProperty('manual_mode_banner_label', None)
        vbox = QVBoxLayout()

        # Manual mode indicator banner
        if is_manual:
            manual_label = QLabel(f"{self._MANUAL_ICON} {self._t('manual_instrument_label')}")
            manual_label.setStyleSheet(
                "QLabel { background-color: #fff3cd; color: #856404; "
                "border: 1px solid #ffc107; border-radius: 4px; padding: 4px; font-weight: bold; }"
            )
            group.setProperty('manual_mode_banner_label', manual_label)
            vbox.addWidget(manual_label)

        # Voltage set with limits
        hbox_v = QHBoxLayout()
        max_voltage = ch.get('max_voltage', 30.0)  # Valore di default
        voltage_label = QLabel(self._t("rc_voltage_range", max=max_voltage))
        hbox_v.addWidget(voltage_label)
        v_edit = QLineEdit()
        v_edit.setPlaceholderText(self._t("rc_max", value=f"{max_voltage}V"))
        # Validazione input voltaggio
        from PyQt6.QtGui import QDoubleValidator
        v_validator = QDoubleValidator(0.0, max_voltage, 3)
        v_edit.setValidator(v_validator)
        set_v_btn = QPushButton(self._t("rc_set"))
        set_v_btn.clicked.connect(lambda _, i=inst, c=ch, e=v_edit: self.set_voltage(i, c, e))
        hbox_v.addWidget(v_edit)
        hbox_v.addWidget(set_v_btn)
        vbox.addLayout(hbox_v)

        # Current set with limits
        hbox_c = QHBoxLayout()
        max_current = ch.get('max_current', 10.0)  # Valore di default
        current_label = QLabel(self._t("rc_current_range", max=max_current))
        hbox_c.addWidget(current_label)
        c_edit = QLineEdit()
        c_edit.setPlaceholderText(self._t("rc_max", value=f"{max_current}A"))
        # Validazione input corrente
        from PyQt6.QtGui import QDoubleValidator
        c_validator = QDoubleValidator(0.0, max_current, 3)
        c_edit.setValidator(c_validator)
        set_c_btn = QPushButton(self._t("rc_set"))
        set_c_btn.clicked.connect(lambda _, i=inst, c=ch, e=c_edit: self.set_current(i, c, e))
        hbox_c.addWidget(c_edit)
        hbox_c.addWidget(set_c_btn)
        vbox.addLayout(hbox_c)

        # Output button and Read button on the same row
        hbox_controls = QHBoxLayout()

        # Output enable/disable button
        output_btn = QPushButton(self._t("rc_output_off"))
        output_btn.setCheckable(True)
        output_btn.setChecked(False)
        output_btn.setStyleSheet("""
            QPushButton {
                padding: 8px;
                font-weight: bold;
                background-color: #d32f2f;
                color: white;
            }
            QPushButton:checked {
                background-color: #2e7d32;
            }
        """)
        output_btn.clicked.connect(lambda checked, i=inst, c=ch, b=output_btn: self.toggle_output(i, c, b, checked))
        hbox_controls.addWidget(output_btn)

        # Add a read actual values button (hidden for manual instruments - nothing to read)
        if not is_manual:
            read_btn = QPushButton(self._t("rc_read_values"))
            hbox_controls.addWidget(read_btn)

        vbox.addLayout(hbox_controls)

        # Label for read values (hidden for manual instruments)
        if not is_manual:
            read_lbl = QLabel('V: ...  I: ...')
            read_btn.clicked.connect(lambda _, i=inst, c=ch, l=read_lbl: self.read_actual(i, c, l))
            vbox.addWidget(read_lbl)

        group.setLayout(vbox)
        print(f"    ✓ widget of channel {ch.get('name', 'N/A')} (manual: {is_manual})")
        return group

    def run_call(self, inst, ch, call, **args):
        """
        Run one logical call (same name and arguments for every brand) on an instrument.
        The planner translates it into the commands of the model, the executor sends them.
        Args:
            inst: Instrument instance data (.inst entry).
            ch: Channel data (its 'channel_id' gives channel_number) or None.
            call: Logical call name, e.g. 'set_voltage'.
            **args: Logical arguments of the call.
        Returns:
            The logical result of the call (None for calls without result).
        Raises:
            ola.call_errors.CallError: call not supported, value not handled, invalid argument,
            step failed, answer not recognised.
        """
        from ola.call_planner import plan_call
        library = self.instruments_manager.get_library() if self.instruments_manager else None
        if inst.get('is_manual', False):
            # not a library model: the operator carries the call out by hand
            if library is None:
                raise CallNotSupportedError("the instrument library is not loaded", call=call)
            handle = manual_handle_from_inst(inst, library, prompt=self._manual_prompt)
            return handle.call(call, **args)
        model_key = inst.get('model_id', inst.get('model', ''))
        model_id = library.resolve_model_id(model_key) if library else None
        if not model_id:
            raise CallNotSupportedError(f"model {model_key!r} is not in the library", call=call)
        instr = self._connected(inst, call)
        visa_addr = inst.get('visa_address', '')
        executor = self._get_instrument_executor(
            visa_addr, instr, inst.get('instance_name', visa_addr), library, model_id)
        if ch is not None and 'channel_number' not in args:
            number = self._extract_channel_number(ch.get('channel_id'))
            if number is not None:
                args['channel_number'] = number
        self._set_remote_once(library, model_id, visa_addr, executor)
        plan = plan_call(library, model_id, call, args)
        return plan.interpret(executor.run(plan))

    def _configure_datalogger(self, inst, channels):
        """
        Configure a datalogger from its .inst entry: the function of every enabled channel
        (configure_dc_voltage, ...) and the scan list (select_channels), so that read_scan
        returns exactly the channels of the project. It is sent again only when the
        configuration in the .inst file changes.
        """
        key = inst.get('instance_name', '')
        done = self.__dict__.setdefault('_datalogger_signature', {})
        sig = datalogger_signature(channels)
        if done.get(key) == sig:
            return
        library = self.instruments_manager.get_library() if self.instruments_manager else None
        model_id = library.resolve_model_id(inst.get('model_id', inst.get('model', ''))) if library else None
        commands = (library.commands(model_id) or {}) if model_id else {}
        supports = (lambda call: call in commands) if commands else None
        for name, args in datalogger_calls(channels, supports):
            self.run_call(inst, None, name, **args)
        done[key] = sig

    def _configure_multimeter(self, inst, ch):
        """
        Configure a multimeter from its .inst entry, as a datalogger is: the function of its
        channel (meas_type) and the automatic range or the range of the file
        (ola.multimeter_setup). It is sent again only when the configuration in the .inst file
        changes. The range calls are sent only if the model has them.
        """
        key = inst.get('instance_name', '')
        done = self.__dict__.setdefault('_multimeter_signature', {})
        sig = multimeter_signature(ch)
        if done.get(key) == sig:
            return
        library = self.instruments_manager.get_library() if self.instruments_manager else None
        model_key = inst.get('model_id', inst.get('model', ''))
        model_id = library.resolve_model_id(model_key) if library else None
        commands = (library.commands(model_id) or {}) if model_id else {}
        for name, args in multimeter_calls(ch, accepts_from(commands)):
            self.run_call(inst, None, name, **args)
        done[key] = sig

    def _set_remote_once(self, library, model_id, visa_addr, executor):
        """
        Serial (RS-232) instruments ignore commands until they are put in remote mode
        (HP E3631A, Keysight 34970A, ...): send the logical call 'set_remote' once per
        connection. Models without that call, or errors, are skipped; the real call that
        follows reports any problem.
        """
        if not str(visa_addr).upper().startswith('ASRL'):
            return
        done = self.__dict__.setdefault('_remote_sent', set())
        if visa_addr in done:
            return
        done.add(visa_addr)
        from ola.call_errors import CallError
        from ola.call_planner import plan_call
        try:
            executor.run(plan_call(library, model_id, 'set_remote', {}))
        except CallError as exc:
            if self.logger:
                self.logger.info(f"set_remote on {visa_addr} skipped: {exc}")

    def get_visa_instrument(self, inst):
        """
        Get the VISA instrument object for the given instance.
        Opens a new connection if not already open.
        :param inst: Instrument instance data.
        :return: VISA instrument object or None if error (or if instrument is manual).
        """
        print(f"[DEBUG] get_visa_instrument for {inst.get('instance_name', 'N/A')}")

        # Manual instruments do not use VISA connections
        if inst.get('is_manual', False):
            print("[DEBUG] manual instrument: no VISA connection")
            return None

        if not self._ensure_visa_initialized():
            print("[DEBUG] VISA not started!")
            return None

        visa_addr = inst.get('visa_address', None)
        print(f"[DEBUG] VISA address: {visa_addr}")

        if not visa_addr:
            print("[DEBUG] no VISA address!")
            return None

        if visa_addr in self.visa_connections:
            print(f"[DEBUG] connection already open for {visa_addr}")
            return self.visa_connections[visa_addr]

        print(f"[DEBUG] opening a connection to {visa_addr}")
        try:
            instr = self.rm.open_resource(visa_addr)
            self._configure_serial(instr, visa_addr, inst)
            self.visa_connections[visa_addr] = instr
            self._open_error = None
            print(f"[DEBUG] connection open: {instr}")
            return instr
        except Exception as e:
            error_msg = f'Cannot open {visa_addr}: {e}'
            print(f"ERROR VISA-002: {error_msg}")
            if self.logger:
                self.logger.error(error_msg, error_code="VISA-002")
            self._open_error = e  # why it is not connected: see _connected
            return None

    def set_voltage(self, inst, ch, edit):
        """
        Set the voltage for the given instrument and channel using the SCPI command.
        :param inst: Instrument instance data.
        :param ch: Channel data.
        :param edit: QLineEdit widget containing the voltage value.
        """
        print(f"[DEBUG] set_voltage for {inst.get('instance_name', 'N/A')}")

        value_str = edit.text().strip()
        if not value_str:
            print("[RemoteControlTab] empty voltage value")
            return

        try:
            value_float = float(value_str)
            max_voltage = ch.get('max_voltage', 30.0)

            # Validazione limiti
            if value_float < 0:
                print(f"[RemoteControlTab] negative voltage refused: {value_float}V")
                return
            elif value_float > max_voltage:
                print(f"[RemoteControlTab] voltage {value_float}V above the limit of {max_voltage}V")
                return

        except ValueError:
            print(f"[RemoteControlTab] invalid voltage value: '{value_str}'")
            return

        print(f"[DEBUG] value checked: {value_float}V")

        # A manual instrument asks the operator (popup) and continues after OK
        if inst.get('is_manual', False):
            try:
                self.run_call(inst, ch, self._setpoint_call(inst, 'voltage'), value=value_float)
            except ManualActionCancelledError as exc:
                print(f"[ManualInstrument] {exc}")
            except Exception as exc:
                self._report_call_error(exc)
            return

        try:
            self.run_call(inst, ch, self._setpoint_call(inst, 'voltage'), value=value_float)
            print(f"[RemoteControlTab] voltage set: {value_float}V on {inst.get('instance_name', 'N/A')}")
        except Exception as e:
            self._report_call_error(e)

    def set_current(self, inst, ch, edit):
        """
        Set the current for the given instrument and channel using the SCPI command.
        :param inst: Instrument instance data.
        :param ch: Channel data.
        :param edit: QLineEdit widget containing the current value.
        """
        print(f"[DEBUG] set_current for {inst.get('instance_name', 'N/A')}")

        value_str = edit.text().strip()
        if not value_str:
            print("[RemoteControlTab] empty current value")
            return

        try:
            value_float = float(value_str)
            max_current = ch.get('max_current', 10.0)

            # Validazione limiti
            if value_float < 0:
                print(f"[RemoteControlTab] negative current refused: {value_float}A")
                return
            elif value_float > max_current:
                print(f"[RemoteControlTab] current {value_float}A above the limit of {max_current}A")
                return

        except ValueError:
            print(f"[RemoteControlTab] invalid current value: '{value_str}'")
            return

        print(f"[DEBUG] value checked: {value_float}A")

        # A manual instrument asks the operator (popup) and continues after OK
        if inst.get('is_manual', False):
            try:
                self.run_call(inst, ch, self._setpoint_call(inst, 'current'), value=value_float)
            except ManualActionCancelledError as exc:
                print(f"[ManualInstrument] {exc}")
            except Exception as exc:
                self._report_call_error(exc)
            return

        try:
            self.run_call(inst, ch, self._setpoint_call(inst, 'current'), value=value_float)
            print(f"[RemoteControlTab] current set: {value_float}A on {inst.get('instance_name', 'N/A')}")
        except Exception as e:
            self._report_call_error(e)

    def toggle_output(self, inst, ch, button, checked):
        """
        Enable or disable the output for the given instrument and channel.
        Usa QTimer per non bloccare il thread GUI durante i tentativi.
        """
        if inst.get('is_manual', False):
            self._toggle_output_manual(inst, ch, button, checked)
            return

        try:
            instr = self._connected(inst, self._output_call(inst, checked))
        except InstrumentNotConnectedError as exc:
            self._report_call_error(exc)
            self._revert_output_button(button, checked)
            return

        self._toggle_output_attempt(instr, inst, ch, button, checked, attempt=1, max_attempts=2)

    def _revert_output_button(self, button, checked):
        """The output button goes back to the state it had before the press."""
        button.setChecked(not checked)
        button.setText(self._t("rc_output_on") if not checked else self._t("rc_output_off"))
        button.setStyleSheet('')

    def _toggle_output_attempt(self, instr, inst, ch, button, checked, attempt, max_attempts):
        """Tenta di impostare l'output e programma la verifica via QTimer."""
        try:
            self.run_call(inst, ch, self._output_call(inst, checked))

            QTimer.singleShot(200, lambda: self._verify_output_state(
                instr, inst, ch, button, checked, attempt, max_attempts))

        except InstrumentNotConnectedError as e:
            # no point in trying again: say so at once
            self._report_call_error(e)
            self._revert_output_button(button, checked)
        except Exception as e:
            if self.logger:
                self.logger.error(f"Toggle Output Error (tentativo {attempt}/{max_attempts}): {e}")
            if attempt < max_attempts:
                QTimer.singleShot(300, lambda: self._toggle_output_attempt(
                    instr, inst, ch, button, checked, attempt + 1, max_attempts))
            else:
                self._toggle_output_failed(inst, ch, button, checked)

    def _verify_output_state(self, instr, inst, ch, button, checked, attempt, max_attempts):
        """Verifica lo stato dell'uscita dopo aver inviato il comando."""
        try:
            try:
                is_on = self.run_call(inst, ch, 'output_state_query')
            except CallNotSupportedError:
                # the model cannot report the output state: trust the command
                self._toggle_output_success(inst, ch, button, checked)
                return

            if is_on == checked:
                self._toggle_output_success(inst, ch, button, checked)
            else:
                if attempt < max_attempts:
                    QTimer.singleShot(300, lambda: self._toggle_output_attempt(
                        instr, inst, ch, button, checked, attempt + 1, max_attempts))
                else:
                    self._toggle_output_failed(inst, ch, button, checked)
        except Exception as e:
            if self.logger:
                self.logger.error(f"Toggle Verify Error: {e}")
            if attempt < max_attempts:
                QTimer.singleShot(300, lambda: self._toggle_output_attempt(
                    instr, inst, ch, button, checked, attempt + 1, max_attempts))
            else:
                self._toggle_output_failed(inst, ch, button, checked)

    def _toggle_output_success(self, inst, ch, button, checked):
        """Aggiorna UI dopo toggle riuscito."""
        if checked:
            button.setText(self._t("rc_output_on"))
            button.setStyleSheet('background-color: #1e7e34; color: white; font-weight: bold;')
        else:
            button.setText(self._t("rc_output_off"))
            button.setStyleSheet('background-color: #dc3545; color: white; font-weight: bold;')
        if self.logger:
            self.logger.info(f"Output {'abilitato' if checked else 'disabilitato'} "
                             f"per {inst.get('instance_name', 'N/A')} - {ch.get('name', 'N/A')}")

    def _toggle_output_failed(self, inst, ch, button, checked):
        """Mostra errore e resetta UI dopo fallimento del toggle."""
        error_title = self._t("rc_output_error_title")
        error_text = self._t(
            "rc_output_on_failed" if checked else "rc_output_off_failed",
            channel=ch.get('name', 'N/A'), instrument=inst.get('instance_name', 'N/A'))
        show_problem(self, error_title, error_text, code="VISA-003", level="critical")
        button.setChecked(not checked)
        button.setText(self._t("rc_output_on") if not checked else self._t("rc_output_off"))
        button.setStyleSheet('')

    def _toggle_output_manual(self, inst, ch, button, checked):
        """Conferma manuale per strumenti non connessi via VISA."""
        try:
            self.run_call(inst, ch, self._output_call(inst, checked))
        except ManualActionCancelledError:
            button.setChecked(not checked)
            return
        except Exception as exc:
            self._report_call_error(exc)
            button.setChecked(not checked)
            return
        if checked:
            button.setText(self._t("rc_output_on"))
            button.setStyleSheet('background-color: #1e7e34; color: white; font-weight: bold;')
        else:
            button.setText(self._t("rc_output_off"))
            button.setStyleSheet('background-color: #dc3545; color: white; font-weight: bold;')

    def read_actual(self, inst, ch, label):
        """
        Read the actual voltage and current values from the instrument and update the label.
        :param inst: Instrument instance data.
        :param ch: Channel data.
        :param label: QLabel widget to update with the read values.
        """
        try:
            v = self.run_call(inst, ch, 'read_voltage')
            c = self.run_call(inst, ch, 'read_current')
            label.setText(f'V: {v:.6g}  I: {c:.6g}')
        except Exception as e:
            label.setText(f"{self._t('error')}: {e}")
            self._report_call_error(e)

    def refresh_measurements_manual(self):
        """Refresh measurements manually (called by button): unlike the automatic refresh it says
        in a box which instruments cannot be read."""
        self.refresh_measurements_auto(manual=True)

    def refresh_measurements_auto(self, manual=False):
        """
        Refresh the measurements displayed in the UI by querying the instruments.
        Nuovo formato: <Nome variabile>=<Valore> <Unità>
        The automatic refresh only marks the values ("NC"); ``manual`` also shows a box.
        """
        if not hasattr(self, 'meas_vars'):
            return
        unreachable = []

        # Dataloggers answer one list with all the readings of the scan list: ask once per
        # instrument and per refresh, then pick the value of each channel by its position
        # (readings follow the order of the enabled channels = scan list order).
        scan_cache = {}

        for inst, ch in self.meas_vars:
            instr = self.get_visa_instrument(inst)
            var_name = ch.get('measured_variable', ch.get('name', 'Unknown'))

            # Determina l'unità di misura corretta
            inst_type = inst.get('instrument_type', '')
            if inst_type in ['multimeter', 'multimeters', 'datalogger', 'dataloggers']:
                # Per multimetri e datalogger usa l'unità specifica dal canale
                unit = ch.get('unit', 'V')
                print(f"[DEBUG] {inst_type} - unit from 'unit': {unit} for {var_name}")
            else:
                # Per altri strumenti usa il default o unit_of_measure
                unit = ch.get('unit_of_measure', 'V')
                print(f"[DEBUG] {inst_type} - unit from 'unit_of_measure': {unit} for {var_name}")

            attenuation = ch.get('attenuation', 1.0)  # Default nessuna attenuazione

            label = self.meas_labels.get((inst.get('instance_name',''), var_name))
            if not label:
                continue

            if not instr:
                # Strumento non connesso
                if inst.get('instance_name', '') not in unreachable:
                    unreachable.append(inst.get('instance_name', ''))
                label.setText(f"{var_name} = NC {unit}")
                label.setProperty("state", "error")
                continue

            try:
                if inst_type in ('datalogger', 'dataloggers'):
                    inst_key = inst.get('instance_name', '')
                    siblings = scan_order([c for i, c in self.meas_vars
                                           if i.get('instance_name', '') == inst_key])
                    if inst_key not in scan_cache:
                        self._configure_datalogger(inst, siblings)
                        scan_cache[inst_key] = self.run_call(inst, None, 'read_scan')
                    readings = scan_cache[inst_key]
                    idx = next((n for n, c in enumerate(siblings) if c is ch), 0)
                    if idx >= len(readings):
                        label.setText(f"{var_name} = N/A {unit}")
                        continue
                    numeric_val = readings[idx]
                else:
                    self._configure_multimeter(inst, ch)
                    numeric_val = float(self.run_call(inst, None, 'read_measurement'))

                final_val = numeric_val / attenuation if attenuation != 0 else numeric_val

                # Formatta il valore con precisione appropriata
                if abs(final_val) >= 1000:
                    formatted_val = f"{final_val:.2f}"
                elif abs(final_val) >= 1:
                    formatted_val = f"{final_val:.3f}"
                else:
                    formatted_val = f"{final_val:.6f}"

                label.setText(f"{var_name} = {formatted_val} {unit}")
                label.setProperty("state", "normal")

            except CallNotSupportedError:
                # the model has no such call: not available, not an instrument error
                label.setText(f"{var_name} = N/A {unit}")
            except InstrumentNotConnectedError as e:
                if self.logger:
                    self.logger.error(f"Measurement error {var_name}: {e}")
                label.setText(f"{var_name} = NC {unit}")
                label.setProperty("state", "error")
                if e.message and inst.get('instance_name', '') not in unreachable:
                    unreachable.append(inst.get('instance_name', ''))
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Measurement error {var_name}: {e}")
                label.setText(f"{var_name} = ERR {unit}")
                label.setProperty("state", "error")

        if manual and unreachable:
            show_problem(
                self, self._t("rc_command_failed"),
                self._t("rc_refresh_not_connected", names=", ".join(n for n in unreachable if n)),
                code="INST-006")

    def toggle_auto_refresh(self, enabled):
        """Abilita/disabilita aggiornamento automatico."""
        if not hasattr(self, 'measurement_timer'):
            return

        if enabled:
            interval = self.interval_slider.value() * 1000  # Converti in ms
            self.measurement_timer.start(interval)
        else:
            self.measurement_timer.stop()

    def update_refresh_interval(self, value):
        """Aggiorna l'intervallo di refresh automatico."""
        self.interval_value_label.setText(f"{value}s")
        if hasattr(self, 'measurement_timer') and self.measurement_timer.isActive():
            self.measurement_timer.setInterval(value * 1000)

    def closeEvent(self, a0):
        """
        Override del metodo closeEvent per pulire tutte le risorse quando il widget viene chiuso.
        """
        try:
            # Stop del timer di misurazione
            if hasattr(self, 'measurement_timer'):
                self.measurement_timer.stop()
            from frontend.ui.VnaPanel import VnaPanel
            for panel in self.findChildren(VnaPanel):
                panel.stop_reading()
            self._close_vna_connector()

            for timer_key, timer in self.connection_timers.items():
                try:
                    timer.stop()
                    timer.deleteLater()
                except RuntimeError:
                    pass
            self.connection_timers.clear()
            for addr, instr in self.visa_connections.items():
                try:
                    instr.close()
                except Exception:
                    logger.debug("Failed to close VISA connection %s during cleanup", addr)
            self.visa_connections.clear()
            self.connection_retry_counts.clear()

            if self.logger:
                self.logger.info("RemoteControlTab: Risorse pulite correttamente")

        except Exception as e:
            if self.logger:
                self.logger.error(f"releasing the resources failed: {e}")
            else:
                print(f"releasing the resources failed: {e}")

        # Chiama il metodo padre
        super().closeEvent(a0)
