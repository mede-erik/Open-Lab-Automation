# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

import json
import logging
logger = logging.getLogger(__name__)
from PyQt6.QtWidgets import (
    QDialog, QHBoxLayout, QListWidget, QFormLayout, QLineEdit, QPushButton, QLabel, QTableWidget, QTableWidgetItem, QCheckBox, QComboBox, QMessageBox, QWidget, QVBoxLayout, QSpinBox, QMenu, QDialogButtonBox, QScrollArea
)
from PyQt6.QtCore import Qt, pyqtSignal, QLocale
from PyQt6.QtGui import QAction, QDoubleValidator
from frontend.ui.AddressEditorDialog import AddressEditorDialog
from frontend.core.Translator import Translator
from frontend.ui.PowerSupplyConfigDialog import PowerSupplyConfigDialog
from frontend.ui.ElectronicLoadConfigDialog import ElectronicLoadConfigDialog
from frontend.ui.OscilloscopeConfigDialog import OscilloscopeConfigDialog
from frontend.ui.DataloggerConfigDialog import DataloggerConfigDialog
from frontend.ui.DataloggerSlotConfigDialog import DataloggerSlotConfigDialog
from frontend.core.LoadInstruments import LoadInstruments
from frontend.ui.InstrumentPanels import NetworkAnalyzerPanel, SerialPanel, SwitchUnitPanel
from ola import inst_file as inst
from ola import project_rename

# PyVISA opzionale per discovery
try:
    import pyvisa
    PYVISA_AVAILABLE = True
except Exception:
    pyvisa = None
    PYVISA_AVAILABLE = False


class InstrumentConfigDialog(QDialog):
    # Emesso ogni volta che la configurazione strumenti viene salvata
    instruments_changed = pyqtSignal(str)  # arg: percorso del file .inst

    def __init__(self, inst_file_path, load_instruments: LoadInstruments, parent=None):
        super().__init__(parent)
        self.translator = Translator()
        self.setWindowTitle(self.translator.t('inst_dialog_title'))
        self.inst_file_path = inst_file_path
        self.load_instruments = load_instruments
        self.extra_keys = {}  # other top-level keys of the file: kept when it is saved
        self.resize(900, 500)
        self.instruments = []
        self.current_instrument = None
        self.suppress_save = False
        self.instruments_modified = False  # Flag per tracciare le modifiche
        self.load_instruments_file()
        self.init_ui()

    def load_instruments_file(self):
        """Read the .inst file. A file that exists but cannot be read is not overwritten: the
        window says so and does not save."""
        try:
            self.instruments, self.extra_keys = inst.load_inst(self.inst_file_path)
        except ValueError as exc:
            self.instruments, self.extra_keys = [], {}
            self.suppress_save = True
            self.load_error = str(exc)
        else:
            self.load_error = ''

    def save_instruments(self):
        if self.suppress_save:
            return
        try:
            # attenuation: a float with at most 10 decimals (no scientific notation)
            def fix_attenuation(obj):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if k == 'channels' and isinstance(v, list):
                            for ch in v:
                                if isinstance(ch.get('attenuation'), float):
                                    ch['attenuation'] = float(f"{ch['attenuation']:.10f}")
                        else:
                            fix_attenuation(v)
                elif isinstance(obj, list):
                    for item in obj:
                        fix_attenuation(item)
            fix_attenuation(self.instruments)
            inst.save_inst(self.inst_file_path, self.instruments, self.extra_keys)
            self.instruments_modified = True  # Segnala che ci sono state modifiche
            # Notifica i listener che il file .inst è stato modificato/salvato
            try:
                self.instruments_changed.emit(self.inst_file_path)
            except Exception:
                logger.debug("Failed to emit instruments_changed signal (no connected slot or deleted receiver)")
        except Exception as e:
            logger.error("Saving the instrument file failed: %s", e)
            QMessageBox.warning(self, self.translator.t('inst_save_error_title'), str(e))

    def init_ui(self):
        t = self.translator.t
        layout = QHBoxLayout(self)

        # Left panel with list and buttons
        left_panel = QVBoxLayout()

        # Button panel
        button_panel = QHBoxLayout()
        add_btn = QPushButton(t('inst_add'))
        add_btn.clicked.connect(self.add_instrument_dialog)
        manual_btn = QPushButton(t('manual_add_button'))
        manual_btn.clicked.connect(self.add_manual_instrument_dialog)
        save_btn = QPushButton(t('inst_save'))
        save_btn.clicked.connect(self.save_instruments)
        # Pulsante: Cerca strumenti nella rete
        discover_btn = QPushButton(t('inst_scan'))
        discover_btn.clicked.connect(self.open_network_scan_dialog)
        button_panel.addWidget(add_btn)
        button_panel.addWidget(manual_btn)
        button_panel.addWidget(save_btn)
        button_panel.addWidget(discover_btn)
        left_panel.addLayout(button_panel)

        if self.load_error:
            error_label = QLabel(t('inst_file_error').format(error=self.load_error))
            error_label.setWordWrap(True)
            error_label.setStyleSheet("color: #b00020;")
            left_panel.addWidget(error_label)

        # Instrument list
        self.list_widget = QListWidget()
        for entry in self.instruments:
            self.list_widget.addItem(self._list_text(entry))
        self.list_widget.currentRowChanged.connect(self.on_instrument_selected)

        # Enable context menu for right-click
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self.show_context_menu)

        left_panel.addWidget(self.list_widget, 1)

        layout.addLayout(left_panel, 2)

        # Editor panel (scrolls: a network analyzer or a serial instrument has many fields)
        self.editor_widget = QWidget()
        self.editor_layout = QVBoxLayout(self.editor_widget)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.editor_widget)
        layout.addWidget(scroll, 5)

        self.refresh_list_marks()
        if self.instruments:
            self.list_widget.setCurrentRow(0)
        else:
            self.show_empty_editor()

    # ---- the problems of the entries --------------------------------------------------------
    def _name_of(self, entry):
        return entry.get('instance_name', entry.get('name', self.translator.t('inst_default_name')))

    def _list_text(self, entry):
        """The name in the list; a warning sign if the entry has problems."""
        name = self._name_of(entry)
        return ('\u26a0 ' if self.entry_problems(entry) else '') + name

    def entry_caps(self, entry):
        """What the library says about the model of an entry (None if it says nothing)."""
        try:
            return self.load_instruments.get_model_capabilities(
                inst.entry_type(entry), entry.get('series', ''), entry.get('model_id'))
        except Exception:
            return None

    def entry_problems(self, entry):
        """The problems of one entry as (code, values) pairs (see ola.inst_file.check_entry)."""
        model_id = entry.get('model_id') or entry.get('model')
        found = True
        if model_id and not entry.get('is_manual'):
            try:
                library = self.load_instruments.get_library()
                found = library.resolve_model_id(model_id) is not None if library else True
            except Exception:
                found = True
        others = [self._name_of(e) for e in self.instruments if e is not entry]
        return inst.check_entry(entry, caps=self.entry_caps(entry), model_found=found,
                                other_names=others)

    def problem_text(self, code, values):
        """A problem in the language of the user."""
        t = self.translator.t
        values = dict(values)
        if 'limit' in values:
            values['limit'] = t('inst_limit_' + str(values['limit']))
        text = t('inst_problem_' + code)
        try:
            return text.format(**values)
        except (KeyError, IndexError, ValueError):
            return text

    def refresh_list_marks(self):
        """Put or remove the warning sign in front of every name of the list."""
        for row, entry in enumerate(self.instruments):
            item = self.list_widget.item(row)
            if item is None:
                continue
            problems = self.entry_problems(entry)
            item.setText(('\u26a0 ' if problems else '') + self._name_of(entry))
            item.setToolTip("\n".join(self.problem_text(c, v) for c, v in problems))

    def refresh_problems(self):
        """Show what is wrong with the selected instrument (and mark the list)."""
        self.refresh_list_marks()
        label = getattr(self, 'problems_label', None)
        if label is None or self.current_instrument is None:
            return
        problems = self.entry_problems(self.current_instrument)
        t = self.translator.t
        if problems:
            lines = ["\u26a0 " + self.problem_text(c, v) for c, v in problems]
            label.setStyleSheet("color: #b00020;")
            label.setText(t('inst_problems_title') + ":\n" + "\n".join(lines))
        else:
            label.setStyleSheet("color: #2e7d32;")
            label.setText("\u2713 " + t('inst_problems_ok'))

    def changed(self):
        """An editor changed the selected entry: save the file and check the entry again."""
        self.save_instruments()
        self.refresh_problems()

    def show_context_menu(self, position):
        """Mostra il menu contestuale per la lista strumenti"""
        item = self.list_widget.itemAt(position)
        if item is None:
            return

        t = self.translator.t
        menu = QMenu(self)
        # Azione duplica strumento
        duplicate_action = QAction(t('inst_duplicate'), self)
        duplicate_action.triggered.connect(self.duplicate_instrument)
        menu.addAction(duplicate_action)

        # Azione cancella strumento
        delete_action = QAction(t('inst_delete'), self)
        delete_action.triggered.connect(self.delete_instrument)
        menu.addAction(delete_action)

        # Mostra il menu solo se c'è almeno un elemento selezionato
        if self.list_widget.currentItem() is not None:
            menu.exec(self.list_widget.mapToGlobal(position))

    def duplicate_instrument(self):
        """Duplica lo strumento selezionato (a new unique name; channels and settings are copied)"""
        current_row = self.list_widget.currentRow()
        if current_row < 0 or current_row >= len(self.instruments):
            return

        import copy
        entry = copy.deepcopy(self.instruments[current_row])
        names = [self._name_of(e) for e in self.instruments]
        entry['instance_name'] = inst.unique_name(self._name_of(entry), names)
        entry.pop('name', None)  # the name of an entry is its instance_name

        self.instruments.append(entry)
        self.list_widget.addItem(self._list_text(entry))
        self.list_widget.setCurrentRow(len(self.instruments) - 1)
        self.save_instruments()
        self.refresh_list_marks()

    def delete_instrument(self):
        """Cancella lo strumento selezionato"""
        current_row = self.list_widget.currentRow()
        if current_row < 0 or current_row >= len(self.instruments):
            return

        t = self.translator.t
        instrument_name = self._name_of(self.instruments[current_row])

        # Chiedi conferma
        reply = QMessageBox.question(
            self,
            t('inst_delete_title'),
            t('inst_delete_question').format(name=instrument_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # Rimuovi dalla lista dati e dalla lista UI. I segnali della lista restano bloccati:
            # takeItem() farebbe emettere currentRowChanged con la riga numerata come prima della
            # rimozione, che non esiste piu' in self.instruments (l'editor resterebbe vuoto).
            del self.instruments[current_row]
            self.list_widget.blockSignals(True)
            try:
                self.list_widget.takeItem(current_row)
                if self.instruments:
                    self.list_widget.setCurrentRow(min(current_row, len(self.instruments) - 1))
            finally:
                self.list_widget.blockSignals(False)

            # Mostra lo strumento che ora e' selezionato (o l'editor vuoto)
            self.on_instrument_selected(self.list_widget.currentRow())

            # Salva automaticamente
            self.save_instruments()
            self.refresh_list_marks()

    def show_empty_editor(self):
        self.clear_editor()
        self.problems_label = None
        label = QLabel(self.translator.t('inst_empty'))
        self.editor_layout.addWidget(label)

    def clear_editor(self):
        """Remove everything from the editor, also the widgets inside nested layouts (they
        would otherwise stay on screen, drawn over the next instrument)."""
        self._clear_layout(self.editor_layout)

    def _clear_layout(self, layout):
        while layout.count():
            child = layout.takeAt(0)
            if child is None:
                continue
            widget = child.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            elif child.layout() is not None:
                self._clear_layout(child.layout())

    def on_instrument_selected(self, row):
        if row < 0 or row >= len(self.instruments):
            self.current_instrument = None
            self.show_empty_editor()
            return
        self.current_instrument = self.instruments[row]
        self.show_instrument_editor(self.current_instrument)

    def show_instrument_editor(self, inst_entry):
        """The editor of one entry: common fields, the panel of its type, and its problems."""
        t = self.translator.t
        self.clear_editor()
        entry = inst_entry
        kind = inst.entry_type(entry)
        manual = entry.get('is_manual', False)
        form = QFormLayout()
        # Nome assegnato
        self.name_edit = QLineEdit(entry.get('instance_name', entry.get('name', '')))
        self.name_edit.textChanged.connect(lambda val: self.check_name(val))
        self.name_edit.editingFinished.connect(self.commit_name)
        form.addRow(t('inst_field_name'), self.name_edit)
        self.name_error = QLabel()
        self.name_error.setStyleSheet("color: #b00020;")
        self.name_error.setVisible(False)
        form.addRow(self.name_error)
        # Address editor (a manual instrument has no address)
        addr_btn = QPushButton(t('inst_address_editor'))
        addr_btn.clicked.connect(self.open_address_editor)
        form.addRow(t('inst_field_address'), addr_btn)
        self.addr_btn = addr_btn
        # Mostra indirizzo attuale
        addr_label = QLabel(entry.get('visa_address', entry.get('address', '')))
        form.addRow(t('visa_address'), addr_label)
        self.addr_label = addr_label
        # Hide address controls AND their row labels for a manual instrument
        for widget in (addr_btn, addr_label):
            widget.setVisible(not manual)
            row_label = form.labelForField(widget)
            if row_label:
                row_label.setVisible(not manual)
        # Tipo strumento
        shown_type = entry.get('instrument_type', entry.get('type', ''))
        type_label = QLabel(t(kind) if kind and t(kind) != kind else shown_type)
        form.addRow(t('inst_field_type'), type_label)
        if not manual:
            self.timeout_spin = QSpinBox()
            self.timeout_spin.setRange(inst.MIN_TIMEOUT_MS, inst.MAX_TIMEOUT_MS)
            self.timeout_spin.setSingleStep(500)
            self.timeout_spin.setValue(int(entry.get('timeout_ms') or inst.DEFAULT_TIMEOUT_MS))
            self.timeout_spin.setToolTip(t('inst_timeout_hint'))
            self.timeout_spin.valueChanged.connect(self.on_timeout_changed)
            form.addRow(t('inst_timeout'), self.timeout_spin)
        self.editor_layout.addLayout(form)
        # What is wrong with this entry (kept up to date while it is edited)
        self.problems_label = QLabel()
        self.problems_label.setWordWrap(True)
        self.editor_layout.addWidget(self.problems_label)
        # RS-232 settings for a serial instrument
        if not manual and str(entry.get('visa_address', '')).upper().startswith('ASRL'):
            self.editor_layout.addWidget(SerialPanel(
                entry, self.serial_defaults(entry), self.translator, self.changed))
        # Editor specifico per tipo
        t_name = kind
        if kind in ('power_supply', 'electronic_load'):
            self.show_channel_table(entry, is_power=True)
        elif kind == 'datalogger':
            # Check if datalogger has slots configuration
            model_id = entry.get('model_id')
            series_id = entry.get('series', '')
            try:
                capabilities = self.load_instruments.get_model_capabilities(t_name, series_id, model_id)
                num_slots = capabilities.get('number_of_slots', 0) if capabilities else 0

                if num_slots > 0:
                    # Datalogger with slots - show slot configuration button
                    self.show_datalogger_slot_config_button(entry)
                else:
                    # Legacy datalogger without slots - show channel table
                    self.show_channel_table(entry, is_power=False)
            except Exception:
                # Fallback to channel table if error
                self.show_channel_table(entry, is_power=False)
        elif kind == 'multimeter':
            self.show_channel_table(entry, is_power=False, is_multimeter=True)
        elif kind == 'oscilloscope':
            # Mostra pulsante per aprire il dialog di configurazione canali oscilloscopio
            self.show_oscilloscope_config_button(entry)
        elif kind == 'network_analyzer':
            self.editor_layout.addWidget(NetworkAnalyzerPanel(
                entry, self.entry_caps(entry), self.translator, self.changed))
        elif kind == 'switch_unit':
            self.editor_layout.addWidget(SwitchUnitPanel(
                entry, self.entry_caps(entry), self.translator, self.changed))
        self.editor_layout.addStretch(1)
        self.refresh_problems()

    def serial_defaults(self, entry):
        """The RS-232 settings the library gives for the model of an entry."""
        try:
            library = self.load_instruments.get_library()
            model_id = library.resolve_model_id(entry.get('model_id') or entry.get('model', ''))
            return {k: v for k, v in library.serial_settings(model_id).items()
                    if k in inst.SERIAL_KEYS} if model_id else {}
        except Exception:
            return {}

    def on_timeout_changed(self, value):
        if self.current_instrument is None:
            return
        if value == inst.DEFAULT_TIMEOUT_MS:
            self.current_instrument.pop('timeout_ms', None)
        else:
            self.current_instrument['timeout_ms'] = int(value)
        self.changed()

    def show_oscilloscope_config_button(self, entry):
        """Mostra un pulsante per configurare i canali dell'oscilloscopio"""
        # Info label
        info_label = QLabel("🔧 " + self.translator.t('inst_osc_info'))
        info_label.setWordWrap(True)
        info_label.setStyleSheet("QLabel { color: #555; padding: 10px; background-color: #f0f0f0; border-radius: 5px; }")
        self.editor_layout.addWidget(info_label)

        # Pulsante per aprire OscilloscopeConfigDialog
        config_btn = QPushButton("⚙️ " + self.translator.t('inst_osc_button'))
        config_btn.setStyleSheet("QPushButton { padding: 10px; font-weight: bold; }")
        config_btn.clicked.connect(lambda: self.open_oscilloscope_config_dialog(entry))
        self.editor_layout.addWidget(config_btn)

        # Mostra riepilogo canali configurati
        channels = entry.get('channels', [])
        if channels:
            enabled_count = sum(1 for ch in channels if ch.get('enabled', False))
            summary_label = QLabel("📊 " + self.translator.t('inst_osc_summary').format(
                total=len(channels), enabled=enabled_count))
            summary_label.setStyleSheet("QLabel { padding: 5px; color: #007acc; }")
            self.editor_layout.addWidget(summary_label)

            # Lista canali abilitati
            if enabled_count > 0:
                enabled_list = QLabel(self.translator.t('inst_osc_enabled') + ": " + ", ".join([
                    f"{ch.get('channel_id', '?')} ({ch.get('name', 'N/A')})"
                    for ch in channels if ch.get('enabled', False)
                ]))
                enabled_list.setWordWrap(True)
                enabled_list.setStyleSheet("QLabel { padding: 5px; font-size: 11px; color: #666; }")
                self.editor_layout.addWidget(enabled_list)

    def open_oscilloscope_config_dialog(self, entry):
        """Apre il dialog di configurazione canali oscilloscopio"""
        dlg = OscilloscopeConfigDialog(entry, self.translator, self, self.load_instruments)
        if dlg.exec():
            # Aggiorna l'interfaccia dopo la configurazione
            self.save_instruments()
            # Ricarica l'editor per mostrare il riepilogo aggiornato
            self.show_instrument_editor(entry)

    def show_datalogger_slot_config_button(self, entry):
        """Show a button to configure datalogger slots and modules"""
        # Info label
        info_label = QLabel("🔧 " + self.translator.t('datalogger_slot_config_desc'))
        info_label.setWordWrap(True)
        info_label.setStyleSheet("QLabel { color: #555; padding: 10px; background-color: #e3f2fd; border-radius: 5px; }")
        self.editor_layout.addWidget(info_label)

        # Button to open DataloggerSlotConfigDialog
        config_btn = QPushButton("⚙️ " + self.translator.t('configure_datalogger_slots'))
        config_btn.setStyleSheet("QPushButton { padding: 10px; font-weight: bold; }")
        config_btn.clicked.connect(lambda: self.open_datalogger_slot_config_dialog(entry))
        self.editor_layout.addWidget(config_btn)

        # Show summary of configured slots
        slots = entry.get('slots', [])
        if slots:
            configured_slots = sum(1 for slot in slots if slot.get('module_id'))
            total_channels = sum(
                len(slot.get('channels', []))
                for slot in slots
                if slot.get('module_id')
            )
            enabled_channels = sum(
                sum(1 for ch in slot.get('channels', []) if ch.get('enabled', False))
                for slot in slots
                if slot.get('module_id')
            )

            summary_label = QLabel(
                f"📊 {self.translator.t('configured_slots')}: {configured_slots}/{len(slots)} | "
                f"{self.translator.t('total_channels')}: {total_channels} | "
                f"{self.translator.t('enabled_channels')}: {enabled_channels}"
            )
            summary_label.setStyleSheet("QLabel { padding: 5px; color: #007acc; }")
            self.editor_layout.addWidget(summary_label)

            # List configured modules
            if configured_slots > 0:
                module_list_parts = []
                for slot in slots:
                    module_id = slot.get('module_id')
                    if module_id:
                        slot_num = slot.get('slot_number', '?')
                        num_ch = len(slot.get('channels', []))
                        module_list_parts.append(f"{self.translator.t('slot')} {slot_num}: {module_id} ({num_ch} ch)")

                modules_list = QLabel(self.translator.t('configured_modules') + ": " + ", ".join(module_list_parts))
                modules_list.setWordWrap(True)
                modules_list.setStyleSheet("QLabel { padding: 5px; font-size: 11px; color: #666; }")
                self.editor_layout.addWidget(modules_list)

    def open_datalogger_slot_config_dialog(self, entry):
        """Open the datalogger slot configuration dialog"""
        dlg = DataloggerSlotConfigDialog(entry, self.load_instruments, self.translator, self)
        if dlg.exec():
            # Update interface after configuration
            self.save_instruments()
            # Reload editor to show updated summary
            self.show_instrument_editor(entry)

    def show_channel_table(self, entry, is_power=False, is_multimeter=False):
        """Mostra la tabella dei canali per lo strumento corrente"""
        # Ricava info capabilities dal modello selezionato
        model_id = entry.get('model_id')
        type_name = entry.get('instrument_type', entry.get('type', '')).lower()
        series_id = entry.get('series', '')

        try:
            model_caps = self.load_instruments.get_model_capabilities(type_name, series_id, model_id)
        except Exception:
            model_caps = None

        n = 0
        if model_caps:
            n = model_caps.get('number_of_channels', entry.get('num_channels', 0))
        else:
            n = entry.get('num_channels', 0)

        if n <= 0:
            # Mostra messaggio informativo invece di non mostrare nulla
            info_label = QLabel("ℹ️ " + self.translator.t('inst_no_channels'))
            info_label.setStyleSheet("QLabel { color: #888; padding: 10px; }")
            self.editor_layout.addWidget(info_label)
            return

        # Ottieni o crea lista canali
        channels = entry.get('channels', [])

        # Sincronizza canali con il numero previsto
        # (channel_ids dal nuovo formato capabilities.channels)
        channel_ids = []
        if model_caps:
            channel_ids = self.load_instruments.get_channel_ids(type_name, series_id, model_id)

        while len(channels) < n:
            idx = len(channels)
            ch_id = channel_ids[idx] if idx < len(channel_ids) else f'CH{idx+1}'
            new_ch = {
                'enabled': False,
                'name': ch_id,
            }
            if is_power:
                limits = self.load_instruments.get_channel_limits(type_name, series_id, model_id)
                new_ch['max_current'] = limits.get('max_current', 0.0)
                new_ch['max_voltage'] = limits.get('max_voltage', 0.0)
                if limits.get('max_power'):
                    new_ch['max_power'] = limits['max_power']
            elif is_multimeter:
                new_ch['meas_type'] = 'DC_V'
                new_ch['attenuation'] = 1.0
                new_ch['unit'] = 'V'
                new_ch['integration_time'] = 0.0
            else:
                # datalogger o altro
                new_ch['meas_type'] = 'DC_V'
                new_ch['unit'] = 'V'
            channels.append(new_ch)

        entry['channels'] = channels[:n]

        # Crea tabella
        if is_power:
            # Power supply / Electronic load
            table = QTableWidget(n, 5)
            table.setHorizontalHeaderLabels([self.translator.t('inst_col_enabled'), self.translator.t('inst_col_name'),
                self.translator.t('inst_col_max_current'), self.translator.t('inst_col_max_voltage'), self.translator.t('inst_col_max_power')])

            for row, ch in enumerate(entry['channels']):
                # Abilita
                chk = QCheckBox()
                chk.setChecked(ch.get('enabled', False))
                chk.stateChanged.connect(lambda state, r=row: self.on_channel_enabled_changed(r, state))
                table.setCellWidget(row, 0, chk)

                # Nome
                name_edit = QLineEdit(ch.get('name', f'CH{row+1}'))
                name_edit.textChanged.connect(lambda val, r=row: self.on_channel_name_changed(r, val))
                table.setCellWidget(row, 1, name_edit)

                # Corrente max
                curr_edit = QLineEdit(str(ch.get('max_current', 0.0)))
                curr_edit.textChanged.connect(lambda val, r=row: self.on_channel_current_changed(r, val))
                table.setCellWidget(row, 2, curr_edit)

                # Tensione max
                volt_edit = QLineEdit(str(ch.get('max_voltage', 0.0)))
                volt_edit.textChanged.connect(lambda val, r=row: self.on_channel_voltage_changed(r, val))
                table.setCellWidget(row, 3, volt_edit)

                # Potenza max (empty: no power limit; the pulse generator checks it when given)
                power = ch.get('max_power')
                power_edit = QLineEdit('' if not power else str(power))
                power_edit.setPlaceholderText(self.translator.t('inst_not_set'))
                power_edit.textChanged.connect(lambda val, r=row: self.on_channel_power_changed(r, val))
                table.setCellWidget(row, 4, power_edit)

        elif is_multimeter:
            # Multimetro
            table = QTableWidget(n, 6)
            table.setHorizontalHeaderLabels([self.translator.t('inst_col_enabled'), self.translator.t('inst_col_name'), self.translator.t('inst_col_meas_type'),
                self.translator.t('inst_col_attenuation'), self.translator.t('inst_col_unit'), self.translator.t('inst_col_integration')])

            for row, ch in enumerate(entry['channels']):
                # Abilita
                chk = QCheckBox()
                chk.setChecked(ch.get('enabled', False))
                chk.stateChanged.connect(lambda state, r=row: self.on_channel_enabled_changed(r, state))
                table.setCellWidget(row, 0, chk)

                # Nome
                name_edit = QLineEdit(ch.get('name', f'CH{row+1}'))
                name_edit.textChanged.connect(lambda val, r=row: self.on_channel_name_changed(r, val))
                table.setCellWidget(row, 1, name_edit)

                # Tipo misura
                meas_combo = QComboBox()
                meas_combo.addItems(['DC_V', 'DC_A', 'AC_V', 'AC_A', 'RES', 'FREQ'])
                meas_combo.setCurrentText(ch.get('meas_type', 'DC_V'))
                meas_combo.currentTextChanged.connect(lambda val, r=row: self.on_channel_meas_type_changed(r, val))
                table.setCellWidget(row, 2, meas_combo)

                # Attenuazione
                # Forza la visualizzazione attenuazione in formato decimale con punto
                att_val = ch.get('attenuation', 1.0)
                if isinstance(att_val, float):
                    att_str = f"{att_val:.10f}".rstrip('0').rstrip('.') if '.' in f"{att_val:.10f}" else str(att_val)
                else:
                    att_str = str(att_val).replace(',', '.')
                att_edit = QLineEdit(att_str)
                # Validator con locale C per forzare il punto decimale
                validator = QDoubleValidator(0.0000000001, 1e6, 10, att_edit)
                validator.setLocale(QLocale(QLocale.Language.C))
                validator.setNotation(QDoubleValidator.Notation.StandardNotation)
                att_edit.setValidator(validator)
                att_edit.setPlaceholderText(self.translator.t('inst_att_placeholder'))
                att_edit.setToolTip(self.translator.t('inst_att_tooltip'))
                att_edit.textChanged.connect(lambda val, r=row: self.on_channel_attenuation_changed(r, val))
                table.setCellWidget(row, 3, att_edit)

                # Unità
                unit_edit = QLineEdit(ch.get('unit', 'V'))
                unit_edit.textChanged.connect(lambda val, r=row: self.on_channel_unit_changed(r, val))
                table.setCellWidget(row, 4, unit_edit)

                # Tempo integrazione
                tint_edit = QLineEdit(str(ch.get('integration_time', 0.0)))
                tint_edit.setValidator(QDoubleValidator(0.0, 1e6, 3, tint_edit))
                tint_edit.setPlaceholderText(self.translator.t('inst_tint_placeholder'))
                tint_edit.textChanged.connect(lambda val, r=row: self.on_channel_integration_time_changed(r, val))
                table.setCellWidget(row, 5, tint_edit)
        else:
            # Datalogger o generico
            # Aggiunta colonna Attenuazione per permettere l'inserimento di shunt/guadagni
            table = QTableWidget(n, 5)
            table.setHorizontalHeaderLabels([self.translator.t('inst_col_enabled'), self.translator.t('inst_col_name'), self.translator.t('inst_col_meas_type'),
                self.translator.t('inst_col_attenuation'), self.translator.t('inst_col_unit')])

            for row, ch in enumerate(entry['channels']):
                # Abilita
                chk = QCheckBox()
                chk.setChecked(ch.get('enabled', False))
                chk.stateChanged.connect(lambda state, r=row: self.on_channel_enabled_changed(r, state))
                table.setCellWidget(row, 0, chk)

                # Nome
                name_edit = QLineEdit(ch.get('name', f'CH{row+1}'))
                name_edit.textChanged.connect(lambda val, r=row: self.on_channel_name_changed(r, val))
                table.setCellWidget(row, 1, name_edit)

                # Tipo misura
                meas_combo = QComboBox()
                meas_combo.addItems(['DC_V', 'DC_A', 'AC_V', 'AC_A', 'RES', 'FREQ', 'TEMP'])
                meas_combo.setCurrentText(ch.get('meas_type', 'DC_V'))
                meas_combo.currentTextChanged.connect(lambda val, r=row: self.on_channel_meas_type_changed(r, val))
                table.setCellWidget(row, 2, meas_combo)

                # Attenuazione (supporta 10 cifre decimali) - visualizzazione forzata decimale con punto
                att_val = ch.get('attenuation', 1.0)
                if isinstance(att_val, float):
                    att_str = f"{att_val:.10f}".rstrip('0').rstrip('.') if '.' in f"{att_val:.10f}" else str(att_val)
                else:
                    att_str = str(att_val).replace(',', '.')
                att_edit = QLineEdit(att_str)
                # Validator con locale C per forzare il punto decimale
                validator = QDoubleValidator(0.0000000001, 1e6, 10, att_edit)
                validator.setLocale(QLocale(QLocale.Language.C))
                validator.setNotation(QDoubleValidator.Notation.StandardNotation)
                att_edit.setValidator(validator)
                att_edit.setPlaceholderText(self.translator.t('inst_att_placeholder'))
                att_edit.setToolTip(self.translator.t('inst_att_tooltip'))
                att_edit.textChanged.connect(lambda val, r=row: self.on_channel_attenuation_changed(r, val))
                table.setCellWidget(row, 3, att_edit)

                # Unità
                unit_edit = QLineEdit(ch.get('unit', 'V'))
                unit_edit.textChanged.connect(lambda val, r=row: self.on_channel_unit_changed(r, val))
                table.setCellWidget(row, 4, unit_edit)

        table.resizeColumnsToContents()
        self.editor_layout.addWidget(table)
        self.channel_table = table

    def name_error_text(self, name):
        """Why ``name`` cannot be the name of the selected instrument ('' if it can)."""
        t = self.translator.t
        taken = [self._name_of(e) for e in self.instruments if e is not self.current_instrument]
        if not name:
            return t('manual_name_required')
        if name in taken:
            return t('manual_name_exists')
        return ''

    def check_name(self, val):
        """While typing: show whether the name can be used (nothing is changed yet)."""
        if self.current_instrument is None:
            return
        error = self.name_error_text(val.strip())
        self.name_error.setText(error)
        self.name_error.setVisible(bool(error))
        self.name_edit.setStyleSheet("border: 1px solid #b00020;" if error else "")

    def commit_name(self):
        """The name was typed (Enter, or the field lost the focus): rename the instrument.

        The name is what measurements use to find the instrument, so an empty or used name is
        refused (the old name comes back) and the measurements that name the instrument are
        updated, after showing which ones, so that none is left pointing at a name that is gone."""
        entry = self.current_instrument
        if entry is None:
            return
        t = self.translator.t
        old, new = self._name_of(entry), self.name_edit.text().strip()
        if new == old:
            self.check_name(old)
            return
        if self.name_error_text(new):
            self.name_edit.setText(old)  # refused: the old name stays
            self.check_name(old)
            return
        references = project_rename.find_references(self.inst_file_path, old)
        if references:
            listing = "\n".join(
                f"\u2022 {r.project} / {r.measurement_name} ({r.role})" for r in references)
            reply = QMessageBox.question(
                self, t('inst_rename_title'),
                t('inst_rename_question').format(
                    count=len({(r.project_path, r.measurement_id) for r in references}),
                    old=old, new=new, list=listing),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if reply != QMessageBox.StandardButton.Yes:
                self.name_edit.setText(old)
                self.check_name(old)
                return
            try:
                project_rename.rename_references(self.inst_file_path, old, new, references)
            except project_rename.RenameError as exc:
                QMessageBox.warning(self, t('inst_rename_title'),
                                    t('inst_rename_failed').format(error=exc))
                self.name_edit.setText(old)
                self.check_name(old)
                return
        entry['instance_name'] = new
        self.save_instruments()
        item = self.list_widget.currentItem()
        if item is not None:
            item.setText(new)
        self.check_name(new)
        self.refresh_problems()

    def open_address_editor(self):
        if self.current_instrument is None:
            return
        dlg = AddressEditorDialog(self.current_instrument, self.load_instruments, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            # Aggiorna indirizzo
            new_address = dlg.get_address()
            if new_address is not None:  # Validazione passata
                self.current_instrument['visa_address'] = new_address
                self.save_instruments()
                self.show_instrument_editor(self.current_instrument)  # serial settings follow
            # Se None, la validazione è fallita e l'utente ha già ricevuto il messaggio di errore
    def open_network_scan_dialog(self):
        """Scansiona le risorse VISA disponibili e permette di applicare un indirizzo allo strumento selezionato."""
        from PyQt6.QtWidgets import QApplication
        if not PYVISA_AVAILABLE or pyvisa is None:
            QMessageBox.information(self, self.translator.t('inst_scan_unavailable_title'), self.translator.t('inst_scan_unavailable'))
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(self.translator.t('inst_scan_title'))
        vbox = QVBoxLayout(dlg)

        # The instrument that gets the address: chosen here, so the window does not depend on what
        # is selected in the editor behind it (the default is that one)
        target_bar = QHBoxLayout()
        target_bar.addWidget(QLabel(self.translator.t('inst_scan_target_label')))
        target_combo = QComboBox()
        for index, entry in enumerate(self.instruments):
            if not entry.get('is_manual'):  # a manual instrument has no address
                target_combo.addItem(self._name_of(entry), index)  # (Qt would copy the dict)
        if self.current_instrument is not None:
            for i in range(target_combo.count()):
                if self.instruments[target_combo.itemData(i)] is self.current_instrument:
                    target_combo.setCurrentIndex(i)

        def target_entry():
            """The instrument chosen in the combo (the real entry of the file), or None."""
            index = target_combo.currentData()
            return self.instruments[index] if index is not None else None
        target_bar.addWidget(target_combo, 1)
        vbox.addLayout(target_bar)

        # What to show: every kind of connection that is checked (all of them at the start)
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel(self.translator.t('inst_scan_show')))
        kind_checks = {}
        for kind, key in (('usb', 'inst_scan_kind_usb'), ('lan', 'inst_scan_kind_lan'),
                          ('rs232', 'inst_scan_kind_rs232'), ('gpib', 'inst_scan_kind_gpib')):
            check = QCheckBox(self.translator.t(key))
            check.setChecked(True)
            kind_checks[kind] = check
            filter_bar.addWidget(check)
        filter_bar.addStretch(1)
        vbox.addLayout(filter_bar)

        table = QTableWidget(0, 3)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setHorizontalHeaderLabels([self.translator.t('inst_scan_col_address'), "IDN", self.translator.t('inst_scan_col_interface')])
        vbox.addWidget(table)

        # What the "Set" button will do (or why it cannot): it is never silent
        status = QLabel()
        status.setWordWrap(True)
        vbox.addWidget(status)

        btns = QDialogButtonBox()
        btn_copy = QPushButton(self.translator.t('inst_scan_copy'))
        btn_apply = QPushButton(self.translator.t('inst_scan_apply'))
        btn_close = QPushButton(self.translator.t('inst_scan_close'))
        btns.addButton(btn_copy, QDialogButtonBox.ButtonRole.ActionRole)
        btns.addButton(btn_apply, QDialogButtonBox.ButtonRole.ActionRole)
        btns.addButton(btn_close, QDialogButtonBox.ButtonRole.RejectRole)
        vbox.addWidget(btns)

        # Esegui discovery
        resources = []
        idn_cache = {}  # addr -> (idn, iface)
        try:
            if pyvisa is not None:
                try:
                    rm = pyvisa.ResourceManager('@py')
                except Exception:
                    rm = pyvisa.ResourceManager()
                try:
                    resources = list(rm.list_resources())
                except Exception:
                    resources = []
                for addr in resources:
                    idn = ""
                    iface = addr.split("::", 1)[0] if "::" in addr else ""
                    try:
                        resource = rm.open_resource(addr)
                        try:
                            resource.timeout = 1000
                        except Exception:
                            logger.debug("Could not set VISA timeout on resource %s", addr)
                        try:
                            setattr(resource, 'write_termination', '\n')
                            setattr(resource, 'read_termination', '\n')
                        except Exception:
                            logger.debug("Could not set terminations on resource %s", addr)
                        try:
                            q = getattr(resource, 'query', None)
                            if callable(q):
                                idn = q("*IDN?")
                            else:
                                w = getattr(resource, 'write', None)
                                r = getattr(resource, 'read', None)
                                if callable(w):
                                    try:
                                        w("*IDN?")
                                    except Exception:
                                        logger.debug("VISA write(*IDN?) failed on %s", addr)
                                if callable(r):
                                    try:
                                        idn = r()
                                    except Exception:
                                        logger.debug("VISA read() failed on %s", addr)
                        except Exception:
                            logger.debug("VISA *IDN? query failed on %s", addr)
                        resource.close()
                    except Exception:
                        logger.debug("Could not open VISA resource %s", addr)
                    idn_cache[addr] = (idn, iface)
        except Exception as e:
            QMessageBox.warning(self, self.translator.t('inst_scan_error_title'), str(e))

        def kind_of(iface_val):
            """Kind of connection of a VISA interface name: usb, lan, rs232, gpib (or 'other')."""
            name = iface_val.upper()
            for prefix, kind in (('USB', 'usb'), ('TCPIP', 'lan'), ('SOCKET', 'lan'),
                                 ('ASRL', 'rs232'), ('GPIB', 'gpib')):
                if name.startswith(prefix):
                    return kind
            return 'other'

        def populate_table():
            """Fill the table with the kinds that are checked (the others are hidden, not lost)."""
            keep = selected_address()
            table.setRowCount(0)
            for addr, (idn_text, iface_val) in idn_cache.items():
                check = kind_checks.get(kind_of(iface_val))
                if check is not None and not check.isChecked():
                    continue  # kinds without a check box ("other") are always shown
                row = table.rowCount()
                table.insertRow(row)
                table.setItem(row, 0, QTableWidgetItem(addr))
                table.setItem(row, 1, QTableWidgetItem(idn_text))
                table.setItem(row, 2, QTableWidgetItem(iface_val))
                if addr == keep:
                    table.selectRow(row)
            table.resizeColumnsToContents()

        table.cellDoubleClicked.connect(lambda row, _col: btn_apply.click())

        def copy_selected():
            row = table.currentRow()
            if row < 0:
                return
            addr_item = table.item(row, 0)
            if addr_item is None:
                return
            addr = addr_item.text()
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(addr)

        def selected_address():
            """The address of the selected row of the table, or None."""
            row = table.currentRow()
            addr_item = table.item(row, 0) if row >= 0 else None
            return addr_item.text() if addr_item is not None else None

        def apply_state():
            """(can_apply, text): what the button does now, or the reason why it cannot."""
            t = self.translator.t
            entry = target_entry()
            if not idn_cache:
                return False, t('inst_scan_none')
            if entry is None:
                return False, t('inst_scan_no_instrument')
            name = self._name_of(entry)
            addr = selected_address()
            if addr is None:
                return False, t('inst_scan_pick').format(name=name)
            return True, t('inst_scan_target').format(address=addr, name=name)

        def refresh_state(*_args):
            can_apply, text = apply_state()
            btn_apply.setEnabled(can_apply)
            status.setText(text)

        def apply_selected():
            can_apply, _text = apply_state()
            if not can_apply:
                refresh_state()
                return
            entry = target_entry()
            entry['visa_address'] = selected_address()
            self.save_instruments()
            if entry is not self.current_instrument:
                self.list_widget.setCurrentRow(self.instruments.index(entry))  # shows it
            else:
                self.show_instrument_editor(entry)  # serial settings follow
            dlg.accept()  # the editor behind now shows the new address

        def refilter(*_args):
            populate_table()
            refresh_state()

        populate_table()
        table.currentCellChanged.connect(refresh_state)
        table.itemSelectionChanged.connect(refresh_state)
        target_combo.currentIndexChanged.connect(refresh_state)
        for check in kind_checks.values():
            check.stateChanged.connect(refilter)
        refresh_state()

        btn_copy.clicked.connect(copy_selected)
        btn_apply.clicked.connect(apply_selected)
        btn_close.clicked.connect(dlg.reject)
        dlg.exec()

    # Metodi di callback per salvataggio immediato
    def on_channel_enabled_changed(self, row, state):
        if self.current_instrument is not None:
            self.current_instrument['channels'][row]['enabled'] = bool(state)
            self.changed()

    def on_channel_name_changed(self, row, val):
        if self.current_instrument is not None:
            self.current_instrument['channels'][row]['name'] = val
            self.changed()

    def _set_limit(self, row, key, val):
        """Store a limit typed in the table (0 if it is not a number: 'limit not set')."""
        if self.current_instrument is not None:
            self.current_instrument['channels'][row][key] = inst.number(val, 0.0) or 0.0
            self.changed()

    def on_channel_current_changed(self, row, val):
        self._set_limit(row, 'max_current', val)

    def on_channel_voltage_changed(self, row, val):
        self._set_limit(row, 'max_voltage', val)

    def on_channel_power_changed(self, row, val):
        """Max power is optional: an empty box removes the limit."""
        if self.current_instrument is None:
            return
        channel = self.current_instrument['channels'][row]
        power = inst.number(val)
        if power and power > 0:
            channel['max_power'] = power
        else:
            channel.pop('max_power', None)
        self.changed()

    def on_channel_meas_type_changed(self, row, val):
        if self.current_instrument is not None:
            self.current_instrument['channels'][row]['meas_type'] = val
            self.changed()

    def on_channel_attenuation_changed(self, row, val):
        if self.current_instrument is not None:
            self.current_instrument['channels'][row]['attenuation'] = inst.number(val, 1.0)
            self.changed()

    def on_channel_unit_changed(self, row, val):
        if self.current_instrument is not None:
            self.current_instrument['channels'][row]['unit'] = val
            self.changed()

    def on_channel_integration_time_changed(self, row, val):
        if self.current_instrument is not None:
            self.current_instrument['channels'][row]['integration_time'] = inst.number(val, 0.0)
            self.changed()

    def add_manual_instrument_dialog(self):
        """
        Add a manual instrument: a generic power supply or electronic load without remote
        control. It is one channel with its limits and is not a model of the instrument
        library (a supply with two outputs is two manual instruments).
        """
        from PyQt6.QtWidgets import QDoubleSpinBox, QMessageBox

        t = self.translator.t
        dlg = QDialog(self)
        dlg.setWindowTitle(t('manual_dialog_title'))
        form = QFormLayout(dlg)
        hint = QLabel(t('manual_dialog_hint'))
        hint.setWordWrap(True)
        form.addRow(hint)
        type_combo = QComboBox()
        type_combo.addItem(t('power_supply'), 'power_supply')
        type_combo.addItem(t('electronic_load'), 'electronic_load')
        form.addRow(t('manual_field_type'), type_combo)
        name_edit = QLineEdit()
        form.addRow(t('manual_field_name'), name_edit)
        volt_spin = QDoubleSpinBox()
        volt_spin.setRange(0.0, 10000.0)
        volt_spin.setDecimals(3)
        form.addRow(t('manual_field_max_voltage'), volt_spin)
        curr_spin = QDoubleSpinBox()
        curr_spin.setRange(0.0, 10000.0)
        curr_spin.setDecimals(3)
        form.addRow(t('manual_field_max_current'), curr_spin)
        power_spin = QDoubleSpinBox()  # 0 = no power limit
        power_spin.setRange(0.0, 1000000.0)
        power_spin.setDecimals(3)
        power_spin.setSpecialValueText(t('inst_not_set'))
        form.addRow(t('manual_field_max_power'), power_spin)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        while dlg.exec() == QDialog.DialogCode.Accepted:
            name = name_edit.text().strip()
            if not name:
                QMessageBox.warning(self, t('manual_dialog_title'), t('manual_name_required'))
                continue
            if any(i.get('instance_name') == name for i in self.instruments):
                QMessageBox.warning(self, t('manual_dialog_title'), t('manual_name_exists'))
                continue
            channel = {
                'enabled': True,
                'name': 'CH1',
                'max_current': curr_spin.value(),
                'max_voltage': volt_spin.value(),
            }
            if power_spin.value() > 0:
                channel['max_power'] = power_spin.value()
            entry = {
                'instrument_type': type_combo.currentData(),
                'instance_name': name,
                'is_manual': True,
                'num_channels': 1,
                'channels': [channel],
            }
            self.instruments.append(entry)
            self.save_instruments()
            self.list_widget.addItem(self._list_text(entry))
            self.list_widget.setCurrentRow(self.list_widget.count() - 1)
            break

    def add_instrument_dialog(self):
        dlg = QDialog(self)
        t = self.translator.t
        dlg.setWindowTitle(t('inst_add'))
        form = QFormLayout(dlg)
        # Tipo: solo quelli presenti in libreria
        type_combo = QComboBox()
        for type_name in self.load_instruments.get_all_types():
            shown = t(type_name)
            type_combo.addItem(shown if shown != type_name else type_name, type_name)
        form.addRow(t('inst_field_type'), type_combo)
        # Serie: aggiornata in base al tipo
        series_combo = QComboBox()
        model_combo = QComboBox()
        model_map = {}
        def update_series():
            series_combo.clear()
            model_combo.clear()
            type_name = type_combo.currentData()
            from PyQt6.QtCore import QSettings
            show_exp = QSettings('LabAutomation', 'App').value('show_experimental_instruments', False, type=bool)
            series_list = self.load_instruments.get_visible_series(type_name, include_experimental=show_exp)
            for s in series_list or []:
                label = s.get('series_name', s.get('series_id', str(s)))
                series_combo.addItem(label, s.get('series_id', label))
            update_models()  # Aggiorna anche i modelli
        def update_models():
            model_combo.clear()
            type_name = type_combo.currentData()
            series_id = series_combo.currentData()
            from PyQt6.QtCore import QSettings
            show_exp = QSettings('LabAutomation', 'App').value('show_experimental_instruments', False, type=bool)
            models = self.load_instruments.get_visible_models(type_name, series_id, include_experimental=show_exp)
            model_map.clear()
            for m in models or []:
                model_name = m.get('name', str(m))
                model_id = m.get('id', model_name)
                num_channels = m.get('channels', m.get('num_channels', 1))
                model_combo.addItem(model_name)
                model_map[model_name] = (model_id, num_channels)
        type_combo.currentIndexChanged.connect(update_series)
        series_combo.currentIndexChanged.connect(update_models)
        update_series()
        form.addRow(t('inst_field_series'), series_combo)
        form.addRow(t('inst_field_model'), model_combo)
        # Nome
        name_edit = QLineEdit()
        form.addRow(t('inst_field_instance_name'), name_edit)
        # Pulsanti
        btns = QHBoxLayout()
        ok_btn = QPushButton(t('inst_btn_add'))
        cancel_btn = QPushButton(t('cancel'))
        btns.addWidget(ok_btn)
        btns.addWidget(cancel_btn)
        form.addRow(btns)
        ok_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            type_name = type_combo.currentData()
            taken = [self._name_of(e) for e in self.instruments]
            name = name_edit.text().strip() or type_name
            if name in taken:  # the name is what measurements use: it must be unique
                name = inst.unique_name(name, taken, suffix='_')
            series = series_combo.currentData()
            model = model_combo.currentText().strip()
            model_id, guessed_num_channels = model_map.get(model, (model, 1))
            # Ricava num_channels dalle capabilities quando possibile
            caps = None
            try:
                caps = self.load_instruments.get_model_capabilities(type_name, series, model_id)
            except Exception:
                caps = None
            num_channels = (
                (caps.get('number_of_channels') if isinstance(caps, dict) else None)
                or (caps.get('channels') if isinstance(caps, dict) and isinstance(caps.get('channels'), int) else None)
                or (caps.get('number_of_slots') if isinstance(caps, dict) else None)
                or guessed_num_channels
            )
            new_inst = {
                'instrument_type': type_name,
                'instance_name': name,
                'series': series,
                'model': model,
                'model_id': model_id,
                'num_channels': num_channels,
                'channels': []
            }
            self.instruments.append(new_inst)
            self.save_instruments()
            self.list_widget.addItem(self._list_text(new_inst))
            self.list_widget.setCurrentRow(self.list_widget.count()-1)
