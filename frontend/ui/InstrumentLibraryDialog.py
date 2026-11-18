# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
                             QTreeWidget, QTreeWidgetItem, QSplitter,
                             QTextEdit, QLabel, QMessageBox, QCheckBox)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtWidgets import QHeaderView, QTreeWidgetItemIterator
from frontend.ui.layout_utils import resize_to_screen
from PyQt6.QtWidgets import QWidget 
from frontend.core.LoadInstruments import LoadInstruments
from frontend.core.errorhandler import show_problem


class InstrumentLibraryDialog(QDialog):
    def __init__(self, load_instruments: LoadInstruments, parent=None, translator=None):
        super().__init__(parent)
        self.translator = translator
        self.load_instruments = load_instruments
        
        # Carica le impostazioni
        self.settings = QSettings('LabAutomation', 'App')
        self.show_experimental = self.settings.value('show_experimental_instruments', False, type=bool)
        
        # Usa translator.t se disponibile, altrimenti lascia la stringa così com'è
        t = getattr(self.translator, 't', None) if self.translator is not None else None
        _ = t if callable(t) else (lambda s: s)
        self.setWindowTitle(str(_('instrument_library')))
        resize_to_screen(self, 1000, 640)

        self.main_layout = QVBoxLayout(self)
        self.setLayout(self.main_layout)

        self.init_ui()

    def _t(self, key):
        """A fixed text of the window in the language of the application (English without one)."""
        if self.translator is None or not callable(getattr(self.translator, 't', None)):
            from frontend.core.Translator import Translator
            self.translator = Translator()
        return str(self.translator.t(key))

    def init_ui(self):
        # Layout principale orizzontale con splitter
        splitter = QSplitter()
        self.main_layout.addWidget(splitter)
        
        # Pannello sinistro: TreeView della libreria
        left_panel = QVBoxLayout()
        left_widget = QWidget()
        left_widget.setLayout(left_panel)
        
        # Etichetta per la vista ad albero
        tree_label = QLabel(self._t("instrument_library"))
        tree_label.setStyleSheet("font-weight: bold; padding: 5px;")
        left_panel.addWidget(tree_label)
        
        # TreeWidget per mostrare la struttura della libreria
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(
            [self._t("ilb_col_name"), self._t("ilb_col_type"), self._t("ilb_col_channels")]
        )
        # the names of the series are long: the first column has a fixed width, they are cut at the end
        header = self.tree_widget.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.tree_widget.setColumnWidth(0, 380)
        self.tree_widget.setTextElideMode(Qt.TextElideMode.ElideRight)
        for column in (1, 2):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.tree_widget.itemClicked.connect(self.on_item_selected)
        left_panel.addWidget(self.tree_widget)
        
        # Checkbox per mostrare strumenti sperimentali
        t = getattr(self.translator, 't', None) if self.translator is not None else None
        _ = t if callable(t) else (lambda s: s)
        
        checkbox_layout = QHBoxLayout()
        self.experimental_checkbox = QCheckBox(str(_('show_experimental_instruments')))
        self.experimental_checkbox.setChecked(self.show_experimental)
        self.experimental_checkbox.stateChanged.connect(self.on_experimental_checkbox_toggled)
        checkbox_layout.addWidget(self.experimental_checkbox)
        checkbox_layout.addStretch()
        left_panel.addLayout(checkbox_layout)
        
        # Pulsanti
        button_layout = QHBoxLayout()
        add_instrument_btn = QPushButton(self._t("ilb_add_new"))
        add_instrument_btn.clicked.connect(self.add_new_instrument)
        refresh_btn = QPushButton(self._t("ilb_refresh"))
        refresh_btn.clicked.connect(self.populate_tree)
        
        button_layout.addWidget(add_instrument_btn)
        button_layout.addWidget(refresh_btn)
        button_layout.addStretch()
        left_panel.addLayout(button_layout)
        
        splitter.addWidget(left_widget)
        
        # Pannello destro: Dettagli dello strumento selezionato
        right_panel = QVBoxLayout()
        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        
        # Etichetta per i dettagli
        details_label = QLabel(self._t("ilb_details_title"))
        details_label.setStyleSheet("font-weight: bold; padding: 5px;")
        right_panel.addWidget(details_label)
        
        # Area di testo per i dettagli
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setPlainText(self._t("ilb_select_hint"))
        right_panel.addWidget(self.details_text)
        
        splitter.addWidget(right_widget)
        
        # Imposta le proporzioni del splitter (70% sinistra, 30% destra)
        splitter.setChildrenCollapsible(False)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([600, 400])
        
        # Popola l'albero inizialmente
        self.populate_tree()

    def add_new_instrument(self):
        """Apre il dialog per aggiungere un nuovo strumento"""
        # Prima chiedi il tipo di strumento
        from frontend.ui.InstrumentTypeSelectionDialog import InstrumentTypeSelectionDialog
        
        type_dialog = InstrumentTypeSelectionDialog(self.load_instruments, self.translator, self)
        if type_dialog.exec() != QDialog.DialogCode.Accepted:
            return
            
        instrument_type = type_dialog.get_selected_type()
        
        # Apri il dialog specifico in base al tipo
        dialog = None
        if instrument_type == "power_supply":
            from frontend.ui.PowerSupplyInstrumentDialog import PowerSupplyInstrumentDialog
            dialog = PowerSupplyInstrumentDialog(self.load_instruments, self.translator, self)
        elif instrument_type == "datalogger":
            from frontend.ui.DataloggerInstrumentDialog import DataloggerInstrumentDialog
            dialog = DataloggerInstrumentDialog(self.load_instruments, self.translator, self)
        elif instrument_type == "electronic_load":
            from frontend.ui.AddInstrumentDialog import AddInstrumentDialog
            dialog = AddInstrumentDialog(self.load_instruments, self.translator, self)
        else:
            # Fallback al dialog generico per altri tipi
            from frontend.ui.AddInstrumentDialog import AddInstrumentDialog
            dialog = AddInstrumentDialog(self.load_instruments, self.translator, self)
        
        if dialog and dialog.exec() == QDialog.DialogCode.Accepted:
            # reload the library, then show the new instrument in the tree
            try:
                from frontend.core.LoadInstruments import get_library_path
                library_path = get_library_path()
                if not self.load_instruments.load_instruments(library_path):
                    raise ValueError(library_path)
                QMessageBox.information(self, self._t("success"), self._t("instrument_added_success"))
            except Exception as e:
                show_problem(self, self._t("warning"), f"{self._t('ilb_reload_failed')}\n{e}", code="LIB-008", exception=e)
            self.populate_tree()

    def populate_tree(self):
        """Popola l'albero con i dati della libreria strumenti"""
        self.tree_widget.clear()
        
        if not self.load_instruments or not hasattr(self.load_instruments, 'instruments'):
            return
            
        # Ottieni tutti i tipi disponibili
        instrument_types = self.load_instruments.get_all_types()
        
        for type_name in instrument_types:
            # Crea nodo principale per il tipo
            type_item = QTreeWidgetItem(self.tree_widget)
            type_display_name = self.get_display_name_for_type(type_name)
            type_item.setText(0, type_display_name)
            type_item.setText(1, self._t("ilb_node_type"))
            type_item.setData(0, 256, {"type": "instrument_type", "key": type_name})  # 256 = Qt.UserRole
            
            # Ottieni le serie per questo tipo (con filtraggio per strumenti sperimentali)
            series_list = self.load_instruments.get_visible_series(type_name, self.show_experimental) or []
            
            for series in series_list:
                # Crea nodo per la serie
                series_item = QTreeWidgetItem(type_item)
                series_name = series.get('series_name', series.get('series_id', self._t('ilb_unknown_series')))
                series_item.setText(0, series_name)
                series_item.setText(1, self._t("ilb_node_series"))
                series_item.setData(0, 256, {"type": "series", "data": series})  # 256 = Qt.UserRole
                
                # Ottieni i modelli per questa serie
                models = series.get('models', [])
                for model in models:
                    # Crea nodo per il modello
                    model_item = QTreeWidgetItem(series_item)
                    model_name = model.get('name', model.get('model', self._t('ilb_unknown_model')))
                    # Aggiungi etichetta "[Sperimentale]" se è un modello sperimentale
                    if model.get('experimental', False):
                        model_name += f" [{self._t('experimental_instrument')}]"
                    model_item.setText(0, model_name)
                    model_item.setText(1, self._t("ilb_node_model"))
                    
                    # Numero di canali se disponibile
                    capabilities = model.get('capabilities', {})
                    # Controlla sia 'number_of_channels' che 'channels'
                    num_channels = capabilities.get('number_of_channels')
                    if num_channels is None:
                        channels = capabilities.get('channels')
                        if isinstance(channels, int):
                            num_channels = channels
                        elif isinstance(channels, list):
                            num_channels = len(channels)
                        else:
                            num_channels = 'N/A'
                    model_item.setText(2, str(num_channels))
                    
                    model_item.setData(0, 256, {"type": "model", "data": model})  # 256 = Qt.UserRole
        
        # Espandi tutti i nodi di primo livello
        self.tree_widget.expandAll()
        # the full name of an item that is cut by the column is in its tooltip
        iterator = QTreeWidgetItemIterator(self.tree_widget)
        while iterator.value():
            item = iterator.value()
            item.setToolTip(0, item.text(0))
            iterator += 1

    def on_experimental_checkbox_toggled(self, state):
        """Gestisce il cambio di stato della checkbox per gli strumenti sperimentali"""
        self.show_experimental = state == Qt.CheckState.Checked.value
        # Salva lo stato nelle impostazioni
        self.settings.setValue('show_experimental_instruments', self.show_experimental)
        self.populate_tree()

    def get_display_name_for_type(self, type_name):
        """The name of an instrument type in the language of the application."""
        shown = self._t(type_name)
        return shown if shown != type_name else type_name.replace('_', ' ').title()

    def on_item_selected(self, item, column):
        """Gestisce la selezione di un elemento nell'albero"""
        if not item:
            return
            
        item_data = item.data(0, 256)  # 256 = Qt.UserRole
        if not item_data:
            return
            
        item_type = item_data.get("type")
        
        if item_type == "instrument_type":
            self.show_type_details(item_data["key"])
        elif item_type == "series":
            self.show_series_details(item_data["data"])
        elif item_type == "model":
            self.show_model_details(item_data["data"])

    def show_type_details(self, type_key):
        """The series of an instrument type (with the filter of the experimental checkbox)."""
        t = self._t
        series_list = self.load_instruments.get_visible_series(type_key, self.show_experimental) or []
        total_models = sum(len(series.get('models', [])) for series in series_list)
        lines = [
            f"{t('ilb_d_type').upper()}: {self.get_display_name_for_type(type_key)}",
            "",
            f"{t('ilb_d_series_count')}: {len(series_list)}",
            f"{t('ilb_d_models_total')}: {total_models}",
            "",
            f"{t('ilb_d_series_list')}:",
        ]
        for series in series_list:
            name = series.get('series_name', t('ilb_unnamed_series'))
            count = t('ilb_d_models').format(count=len(series.get('models', [])))
            lines.append(f"• {name} ({count})")
        self.details_text.setPlainText("\n".join(lines) + "\n")

    def show_series_details(self, series_data):
        """The models and the common commands of a series."""
        t = self._t
        models = series_data.get('models', [])
        lines = [
            f"{t('ilb_d_series').upper()}: {series_data.get('series_name', t('ilb_unnamed_series'))}",
            "",
            f"{t('ilb_d_series_id')}: {series_data.get('series_id', 'N/A')}",
            f"{t('ilb_d_models_count')}: {len(models)}",
            "",
            f"{t('ilb_d_common_commands')}:",
        ]
        for cmd_name, cmd_value in series_data.get('common_scpi_commands', {}).items():
            lines.append(f"• {cmd_name}: {self._format_scpi_command(cmd_value)}")
        if models:
            lines += ["", f"{t('ilb_d_models_in_series')}:"]
            for model in models:
                channels = model.get('capabilities', {}).get('number_of_channels', 'N/A')
                name = model.get('name', t('ilb_unnamed_model'))
                lines.append(f"• {name} ({t('ilb_d_channels').format(count=channels)})")
        self.details_text.setPlainText("\n".join(lines) + "\n")

    def show_model_details(self, model_data):
        """Everything the library says about a model."""
        t = self._t
        yes_no = {True: t('ilb_yes'), False: t('ilb_no')}
        lines = [
            f"{t('ilb_d_model').upper()}: {model_data.get('name', t('ilb_unnamed_model'))}",
            "",
            f"{t('ilb_d_manufacturer')}: {model_data.get('manufacturer', 'N/A')}",
            f"{t('ilb_d_model_id')}: {model_data.get('id', 'N/A')}",
            f"{t('ilb_d_documentation')}: {model_data.get('documentation_path', 'N/A')}",
            "",
        ]
        capabilities = model_data.get('capabilities', {})
        if capabilities:
            lines.append(f"{t('ilb_d_capabilities').upper()}:")
            number_of_channels = capabilities.get('number_of_channels', 0)
            lines.append(f"• {t('ilb_d_channel_count')}: {capabilities.get('number_of_channels', 'N/A')}")
            if 'read_voltage' in capabilities:
                lines.append(f"• {t('ilb_d_reads_voltage')}: {yes_no[bool(capabilities['read_voltage'])]}")
            if 'read_current' in capabilities:
                lines.append(f"• {t('ilb_d_reads_current')}: {yes_no[bool(capabilities['read_current'])]}")
            channels = capabilities.get('channels', [])
            if isinstance(channels, list) and channels:
                lines += ["", f"{t('ilb_d_channels_available').format(count=len(channels))}:"]
                for i, channel in enumerate(channels):
                    if isinstance(channel, dict):
                        ch_id = channel.get('channel_id', f'CH{i+1}')
                        lines.append(f"• {ch_id}: {channel.get('label', 'N/A')}")
            elif isinstance(channels, int) and channels > 0:
                lines += ["", f"{t('ilb_d_channel_count')}: {channels}"]
            elif isinstance(number_of_channels, int) and number_of_channels > 0:
                lines += ["", f"{t('ilb_d_channel_count')}: {number_of_channels}"]
        connection_types = model_data.get('interface', {}).get('supported_connection_types', [])
        if connection_types:
            lines += ["", f"{t('ilb_d_interfaces')}:"]
            for conn in connection_types:
                lines.append(f"• {conn.get('type', 'N/A')}: {conn.get('address_format_example', 'N/A')}")
        scpi_commands = model_data.get('scpi_commands', {})
        if scpi_commands:
            lines += ["", f"{t('ilb_d_model_commands')}:"]
            for cmd_name, cmd_value in scpi_commands.items():
                lines.append(f"• {cmd_name}: {self._format_scpi_command(cmd_value)}")
        notes = model_data.get('notes', '')
        if notes:
            lines += ["", f"{t('ilb_d_notes')}:", str(notes)]
        self.details_text.setPlainText("\n".join(lines) + "\n")

    def _format_scpi_command(self, command_def):
        """Formatta un comando SCPI per la visualizzazione, compatibile con vecchio formato."""
        if isinstance(command_def, str):
            return command_def
        if command_def is None:
            return self._t("ilb_not_supported")
        if not isinstance(command_def, dict):
            return "N/A"
        if 'patch' in command_def and 'set' not in command_def and 'query' not in command_def:
            return f"patch: {command_def.get('patch')}"
        set_def = command_def.get('set')
        query_def = command_def.get('query')
        parts = []
        if isinstance(set_def, dict) and set_def.get('syntax'):
            parts.append(f"set: {set_def.get('syntax')}")
        elif isinstance(set_def, dict) and set_def.get('steps'):
            parts.append("set: " + " ; ".join(s.get('text', s.get('op', '')) for s in set_def['steps']))
        if isinstance(query_def, dict) and query_def.get('syntax'):
            parts.append(f"query: {query_def.get('syntax')}")
        elif isinstance(query_def, dict) and query_def.get('steps'):
            parts.append("query: " + " ; ".join(s.get('text', s.get('op', '')) for s in query_def['steps']))
        if parts:
            return " | ".join(parts)
        return "N/A"