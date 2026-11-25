# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

import logging
logger = logging.getLogger(__name__)
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel
from frontend.ui.theme_utils import set_class
from frontend.core.errorhandler import show_problem
from ola import was_editor
from ola.was_editor import WasEditor

# =========================
# WasFileDialog
# =========================
class WasFileDialog(QDialog):
    """
    Dialog per la modifica di un file .was (oscilloscope settings).
    Permette di configurare i canali abilitati, volt/div per canale e tempo/div globale.
    """
    def __init__(self, file_path, translator, project_data=None, parent=None):
        """
        Inizializza la finestra di dialogo per la modifica di un file .was.
        :param file_path: Percorso del file .was da modificare.
        :param translator: Istanza del traduttore per la localizzazione.
        :param project_data: Dati del progetto (opzionale, per recuperare info strumenti)
        :param parent: Widget genitore.
        """
        super().__init__(parent)
        from PyQt6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, 
                                      QPushButton)
        self.translator = translator
        self.file_path = file_path
        self.project_data = project_data
        self.setWindowTitle(self.translator.t('edit_was_file'))
        self.setModal(True)
        
        # Layout principale orizzontale: sinistra parametri, destra JSON
        main_layout = QHBoxLayout()
        
        # --- Sezione sinistra: parametri ---
        left_layout = QVBoxLayout()
        
        # --- Sezione Canali Oscilloscopio ---
        self.setup_channels_section(left_layout)
        
        # --- Sezione Tempo/Div ---
        self.setup_timing_section(left_layout)

        # --- Sezione Trigger ---
        self.setup_trigger_section(left_layout)
        
        # Pulsante per applicare i parametri al JSON
        self.apply_params_btn = QPushButton(self.translator.t('apply_to_data'))
        self.apply_params_btn.clicked.connect(self.apply_params_to_json)
        left_layout.addWidget(self.apply_params_btn)
        left_layout.addStretch()
        
        # --- Sezione destra: editor JSON ---
        right_layout = QVBoxLayout()
        self.data_edit = QTextEdit()
        
        # Carica il contenuto del file .was (la logica è in ola/was_editor.py)
        self.editor = WasEditor.load(self.file_path)
        self.data_edit.setText(self.editor.text())

        right_layout.addWidget(QLabel(self.translator.t('oscilloscope_settings_data')))
        right_layout.addWidget(self.data_edit)
        
        # Pulsante per salvare le modifiche
        save_btn = QPushButton(self.translator.t('save'))
        save_btn.clicked.connect(self.save_changes)
        right_layout.addWidget(save_btn)
        
        # --- Unione layout ---
        main_layout.addLayout(left_layout, 1)
        main_layout.addLayout(right_layout, 2)
        self.setLayout(main_layout)
        
        # Precompila i parametri a sinistra se già presenti nel JSON
        self.populate_params_from_json()
        
        # Sincronizza i parametri se il JSON viene modificato manualmente
        self.data_edit.textChanged.connect(self.sync_params_from_json)

    def get_oscilloscopes(self):
        """The oscilloscopes of the project's .inst file: instance_name, model_id, channels."""
        import os

        inst_file = (self.project_data or {}).get('inst_file')
        if not inst_file:
            return []
        return was_editor.oscilloscopes(os.path.join(os.path.dirname(self.file_path), inst_file))

    def get_oscilloscope_channels(self, instance_name=None):
        """The channels of one oscilloscope of the project (the first if no name is given)."""
        return was_editor.channels_of(self.get_oscilloscopes(), instance_name)

    @property
    def data(self):
        """The content of the file (see ola/was_editor.py)."""
        return self.editor.data

    def setup_channels_section(self, layout):
        """
        Crea la sezione per configurare i canali dell'oscilloscopio.
        Permette di selezionare l'oscilloscopio quando il progetto ne ha più di uno.
        """
        from PyQt6.QtWidgets import QGroupBox, QComboBox, QHBoxLayout

        self.scopes = self.get_oscilloscopes()
        self.channel_widgets = []

        group = QGroupBox(self.translator.t('oscilloscope_channels'))
        group_layout = QVBoxLayout()

        if self.scopes:
            # Selettore oscilloscopio
            selector_layout = QHBoxLayout()
            selector_label = QLabel(self.translator.t('select_oscilloscope'))
            self.scope_combo = QComboBox()
            for s in self.scopes:
                label = s['instance_name']
                if s['model_id']:
                    label += f" ({s['model_id']})"
                self.scope_combo.addItem(label, s['instance_name'])
            self.scope_combo.currentIndexChanged.connect(self.on_scope_changed)
            selector_layout.addWidget(selector_label)
            selector_layout.addWidget(self.scope_combo, 1)
            group_layout.addLayout(selector_layout)
        else:
            # Nessun oscilloscopio configurato - mostra canali di default
            info_label = QLabel(self.translator.t('no_oscilloscope_configured'))
            info_label.setWordWrap(True)
            set_class(info_label, "warning")
            group_layout.addWidget(info_label)

        self.channels_group_layout = group_layout
        self._channel_layouts = []
        group.setLayout(group_layout)
        layout.addWidget(group)

        # Crea i widget canali per l'oscilloscopio selezionato (o default)
        channels = self.get_oscilloscope_channels() or []
        if not channels:
            channels = was_editor.default_channels()
        self._rebuild_channel_widgets(channels)

    def on_scope_changed(self, index):
        """Ricostruisce i widget canali quando cambia l'oscilloscopio selezionato."""
        instance_name = self.scope_combo.itemData(index) if self.scopes else None
        channels = self.get_oscilloscope_channels(instance_name)
        if not channels:
            channels = []
        self._rebuild_channel_widgets(channels)
        # Aggiorna i canali disponibili per la sorgente trigger
        self._update_trigger_source_combo()
        # Riapplica i valori del file .was sui nuovi widget
        if hasattr(self, 'editor'):
            self.populate_params_from_json()

    def _rebuild_channel_widgets(self, channels):
        """Rigenera i widget dei canali nel layout del gruppo."""
        from PyQt6.QtWidgets import QVBoxLayout, QCheckBox, QLabel, QComboBox

        # Rimuove i layout dei canali precedentemente creati (selettore/info restano)
        for sub in self._channel_layouts:
            while sub.count():
                sub_item = sub.takeAt(0)
                if sub_item.widget():
                    sub_item.widget().deleteLater()
            self.channels_group_layout.removeItem(sub)
            if hasattr(sub, 'deleteLater'):
                sub.deleteLater()
        self._channel_layouts = []

        self.channel_widgets = []
        for ch in channels:
            ch_layout = QVBoxLayout()

            # Checkbox per abilitare il canale
            ch_enable = QCheckBox(f"{ch.get('channel_id', 'CH?')} - {ch.get('name', 'Signal')}")
            ch_enable.setChecked(ch.get('enabled', False))
            ch_layout.addWidget(ch_enable)

            # Combobox per Volt/div
            volt_label = QLabel(self.translator.t('volt_per_div'))
            volt_combo = QComboBox()
            volt_combo.addItems(was_editor.VOLT_OPTIONS)
            current_vdiv = ch.get('volt_per_div', '1V')
            idx = volt_combo.findText(current_vdiv)
            if idx >= 0:
                volt_combo.setCurrentIndex(idx)

            ch_layout.addWidget(volt_label)
            ch_layout.addWidget(volt_combo)

            # Salva riferimenti ai widget
            self.channel_widgets.append({
                'channel_id': ch.get('channel_id', f'CH{len(self.channel_widgets)+1}'),
                'name': ch.get('name', 'Signal'),
                'enable_widget': ch_enable,
                'volt_div_widget': volt_combo,
                'probe_attenuation': ch.get('probe_attenuation', 1.0)
            })

            self.channels_group_layout.addLayout(ch_layout)
            self._channel_layouts.append(ch_layout)

    def setup_timing_section(self, layout):
        """
        Crea la sezione per configurare il tempo/div.
        """
        from PyQt6.QtWidgets import QGroupBox, QFormLayout, QLineEdit
        
        group = QGroupBox(self.translator.t('timing_settings'))
        form = QFormLayout()
        
        # Campo per tempo/div (accetta anche notazione 100k, 1n1, ecc.)
        self.time_div_edit = QLineEdit()
        self.time_div_edit.setPlaceholderText(self.translator.t('time_div_placeholder'))
        form.addRow(self.translator.t('time_div_label'), self.time_div_edit)

        # reset the instrument first (the default), or apply only what this file says
        from PyQt6.QtWidgets import QCheckBox
        self.reset_check = QCheckBox(self.translator.t('was_reset'))
        self.reset_check.setToolTip(self.translator.t('was_reset_help'))
        self.reset_check.setChecked(True)
        self.reset_check.toggled.connect(self.apply_params_to_json)
        form.addRow(self.reset_check)

        group.setLayout(form)
        layout.addWidget(group)

    def setup_trigger_section(self, layout):
        """
        Crea la sezione per configurare il trigger: sorgente (canale), fronte
        (rise/fall), livello e modalità.
        """
        from PyQt6.QtWidgets import QGroupBox, QFormLayout, QComboBox, QLineEdit
        from PyQt6.QtGui import QDoubleValidator

        group = QGroupBox(self.translator.t('trigger_settings'))
        form = QFormLayout()

        # Sorgente trigger (canali dell'oscilloscopio selezionato)
        self.trigger_source_combo = QComboBox()
        form.addRow(self.translator.t('trigger_source'), self.trigger_source_combo)

        # Fronte trigger (rise/fall)
        self.trigger_slope_combo = QComboBox()
        self.trigger_slope_combo.addItem(self.translator.t('trigger_rise'), 'RISE')
        self.trigger_slope_combo.addItem(self.translator.t('trigger_fall'), 'FALL')
        form.addRow(self.translator.t('trigger_slope'), self.trigger_slope_combo)

        # Livello trigger (volt)
        self.trigger_level_edit = QLineEdit()
        self.trigger_level_edit.setPlaceholderText("1.5")
        validator = QDoubleValidator(-10000.0, 10000.0, 3, self.trigger_level_edit)
        self.trigger_level_edit.setValidator(validator)
        form.addRow(self.translator.t('trigger_level'), self.trigger_level_edit)

        # Modalità trigger
        self.trigger_mode_combo = QComboBox()
        self.trigger_mode_combo.addItem('AUTO', 'AUTO')
        self.trigger_mode_combo.addItem('NORM', 'NORM')
        form.addRow(self.translator.t('trigger_mode'), self.trigger_mode_combo)

        group.setLayout(form)
        layout.addWidget(group)

        # Popola la combo sorgente con i canali dell'oscilloscopio selezionato
        self._update_trigger_source_combo()

    def _update_trigger_source_combo(self):
        """
        Aggiorna la combo sorgente trigger con i canali dell'oscilloscopio selezionato.
        Preserva la selezione se il canale è ancora disponibile.
        """
        if not hasattr(self, 'trigger_source_combo'):
            return
        current = self.trigger_source_combo.currentData()
        self.trigger_source_combo.blockSignals(True)
        self.trigger_source_combo.clear()
        channel_ids = [w['channel_id'] for w in getattr(self, 'channel_widgets', [])]
        if not channel_ids:
            channel_ids = ['CH1', 'CH2', 'CH3', 'CH4']
        for cid in channel_ids:
            self.trigger_source_combo.addItem(cid, cid)
        if current and self.trigger_source_combo.findData(current) >= 0:
            self.trigger_source_combo.setCurrentIndex(self.trigger_source_combo.findData(current))
        self.trigger_source_combo.blockSignals(False)

    def _parse_voltage(self, s):
        """'1,5' -> 1.5, or None."""
        return was_editor.parse_level(s)

    def trigger_values(self):
        """
        Ritorna il dict trigger {source, slope, level, mode} dai widget della sezione.
        Level è incluso solo se valorizzato correttamente.
        """
        source = self.trigger_source_combo.currentData()
        if not source:
            return None
        values = {
            'source': source,
            'slope': self.trigger_slope_combo.currentData(),
            'mode': self.trigger_mode_combo.currentData(),
        }
        level_edit = getattr(self, 'trigger_level_edit', None)
        level = self._parse_voltage(level_edit.text()) if level_edit else None
        if level is not None:
            values['level'] = level
        return values


    def parse_time(self, s):
        """A time in seconds from '1ms', '100us', '1e-3'...; None if invalid."""
        return was_editor.parse_time(s)

    def populate_params_from_json(self):
        """Fill the form on the left from the content of the file."""
        form = self.editor.form()
        if hasattr(self, 'reset_check'):
            self.reset_check.blockSignals(True)
            self.reset_check.setChecked(form['reset'])
            self.reset_check.blockSignals(False)
        if form['time_per_div'] and hasattr(self, 'time_div_edit'):
            self.time_div_edit.setText(form['time_per_div'])
        for ch_widget in getattr(self, 'channel_widgets', []):
            found = form['channels'].get(ch_widget['channel_id'])
            if found:
                enabled, vdiv = found
                ch_widget['enable_widget'].setChecked(enabled)
                idx = ch_widget['volt_div_widget'].findText(vdiv)
                if idx >= 0:
                    ch_widget['volt_div_widget'].setCurrentIndex(idx)
        trigger = form['trigger']
        if hasattr(self, 'trigger_source_combo'):
            src = trigger.get('source')
            if src and self.trigger_source_combo.findData(src) >= 0:
                self.trigger_source_combo.setCurrentIndex(self.trigger_source_combo.findData(src))
            idx = self.trigger_slope_combo.findData(trigger.get('slope', 'RISE'))
            if idx >= 0:
                self.trigger_slope_combo.setCurrentIndex(idx)
            if 'level' in trigger:
                self.trigger_level_edit.setText(str(trigger['level']))
            idx = self.trigger_mode_combo.findData(trigger.get('mode', 'AUTO'))
            if idx >= 0:
                self.trigger_mode_combo.setCurrentIndex(idx)

    def apply_params_to_json(self):
        """Put the form in the content of the file and show it in the JSON editor."""
        self.editor.apply(
            reset=self.reset_check.isChecked() if hasattr(self, 'reset_check') else True,
            time_text=self.time_div_edit.text() if hasattr(self, 'time_div_edit') else '',
            channels=[
                {
                    'channel_id': w['channel_id'],
                    'name': w['name'],
                    'enabled': w['enable_widget'].isChecked(),
                    'volt_per_div': w['volt_div_widget'].currentText(),
                    'probe_attenuation': w.get('probe_attenuation', 1.0),
                }
                for w in getattr(self, 'channel_widgets', [])
            ],
            trigger=self.trigger_values(),
        )
        self.data_edit.setText(self.editor.text())

    def sync_params_from_json(self):
        """Update the form when the JSON is edited by hand."""
        try:
            self.editor.set_text(self.data_edit.toPlainText())
        except ValueError:
            logger.warning("Failed to sync params from JSON (invalid JSON in editor)")
            return
        self.populate_params_from_json()

    def save_changes(self):
        """
        Salva i dati attuali nel file .was e chiude la dialog.
        Mostra un messaggio di errore se il salvataggio fallisce.
        """
        try:
            self.editor.save(self.file_path)
            self.accept()
        except Exception as e:
            show_problem(self, self.translator.t('error'), str(e), code="FILE-006", exception=e)

