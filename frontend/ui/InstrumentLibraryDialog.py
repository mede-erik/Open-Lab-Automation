import sys
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, 
                             QTreeWidget, QTreeWidgetItem, QSplitter, 
                             QTextEdit, QLabel, QMessageBox)
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget 
from frontend.core.LoadInstruments import LoadInstruments


class InstrumentLibraryDialog(QDialog):
    def __init__(self, load_instruments: LoadInstruments, parent=None, translator=None):
        super().__init__(parent)
        self.translator = translator
        self.load_instruments = load_instruments
        # Usa translator.t se disponibile, altrimenti lascia la stringa così com'è
        t = getattr(self.translator, 't', None) if self.translator is not None else None
        _ = t if callable(t) else (lambda s: s)
        self.setWindowTitle(str(_('Instrument Library')))
        self.setGeometry(100, 100, 900, 600)

        self.main_layout = QVBoxLayout(self)
        self.setLayout(self.main_layout)

        self.init_ui()

    def init_ui(self):
        # Layout principale orizzontale con splitter
        splitter = QSplitter()
        self.main_layout.addWidget(splitter)
        
        # Pannello sinistro: TreeView della libreria
        left_panel = QVBoxLayout()
        left_widget = QWidget()
        left_widget.setLayout(left_panel)
        
        # Etichetta per la vista ad albero
        tree_label = QLabel("Libreria Strumenti")
        tree_label.setStyleSheet("font-weight: bold; padding: 5px;")
        left_panel.addWidget(tree_label)
        
        # TreeWidget per mostrare la struttura della libreria
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderLabels(["Nome", "Tipo", "Canali"])
        self.tree_widget.itemClicked.connect(self.on_item_selected)
        left_panel.addWidget(self.tree_widget)
        
        # Pulsanti
        button_layout = QHBoxLayout()
        add_instrument_btn = QPushButton("Aggiungi Nuovo Strumento")
        add_instrument_btn.clicked.connect(self.add_new_instrument)
        refresh_btn = QPushButton("Aggiorna")
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
        details_label = QLabel("Dettagli Strumento")
        details_label.setStyleSheet("font-weight: bold; padding: 5px;")
        right_panel.addWidget(details_label)
        
        # Area di testo per i dettagli
        self.details_text = QTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setPlainText("Seleziona uno strumento per vedere i dettagli")
        right_panel.addWidget(self.details_text)
        
        splitter.addWidget(right_widget)
        
        # Imposta le proporzioni del splitter (70% sinistra, 30% destra)
        splitter.setSizes([500, 300])
        
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
        if instrument_type == "power_supplies":
            from frontend.ui.PowerSupplyInstrumentDialog import PowerSupplyInstrumentDialog
            dialog = PowerSupplyInstrumentDialog(self.load_instruments, self.translator, self)
        elif instrument_type == "dataloggers":
            from frontend.ui.DataloggerInstrumentDialog import DataloggerInstrumentDialog
            dialog = DataloggerInstrumentDialog(self.load_instruments, self.translator, self)
        elif instrument_type == "oscilloscopes":
            from frontend.ui.AddInstrumentDialog import AddInstrumentDialog
            dialog = AddInstrumentDialog(self.load_instruments, self.translator, self)
        else:
            # Fallback al dialog generico per altri tipi
            from frontend.ui.AddInstrumentDialog import AddInstrumentDialog
            dialog = AddInstrumentDialog(self.load_instruments, self.translator, self)
        
        if dialog and dialog.exec() == QDialog.DialogCode.Accepted:
            # Ricarica la libreria strumenti
            try:
                import os
                base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                library_path = os.path.join(base_path, 'Instruments_LIB', 'instruments_lib.json')
                self.load_instruments.load_instruments(library_path)
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(self, self.translator.get("success", "Successo"), self.translator.get("instrument_added_success", "Strumento aggiunto con successo alla libreria!"))
            except Exception as e:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(self, self.translator.get("warning", "Attenzione"), f"{self.translator.get('reload_library_warning', 'Strumento aggiunto ma errore nel ricaricamento:')}\n{str(e)}")
            # Aggiorna la vista ad albero
            self.populate_tree()

    def populate_tree(self):
        """Popola l'albero con i dati della libreria strumenti"""
        self.tree_widget.clear()
        
        if not self.load_instruments or not hasattr(self.load_instruments, 'instruments'):
            return
            
        instruments_data = self.load_instruments.instruments
        
        # Ottieni tutti i tipi disponibili
        instrument_types = self.load_instruments.get_all_types()
        
        for type_name in instrument_types:
            # Crea nodo principale per il tipo
            type_item = QTreeWidgetItem(self.tree_widget)
            type_display_name = self.get_display_name_for_type(type_name)
            type_item.setText(0, type_display_name)
            type_item.setText(1, "Tipo")
            type_item.setData(0, 256, {"type": "instrument_type", "key": type_name})  # 256 = Qt.UserRole
            
            # Ottieni le serie per questo tipo
            series_list = self.load_instruments.get_series(type_name) or []
            
            for series in series_list:
                # Crea nodo per la serie
                series_item = QTreeWidgetItem(type_item)
                series_name = series.get('series_name', series.get('series_id', 'Serie sconosciuta'))
                series_item.setText(0, series_name)
                series_item.setText(1, "Serie")
                series_item.setData(0, 256, {"type": "series", "data": series})  # 256 = Qt.UserRole
                
                # Ottieni i modelli per questa serie
                models = series.get('models', [])
                for model in models:
                    # Crea nodo per il modello
                    model_item = QTreeWidgetItem(series_item)
                    model_name = model.get('name', model.get('model', 'Modello sconosciuto'))
                    model_item.setText(0, model_name)
                    model_item.setText(1, "Modello")
                    
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

    def get_display_name_for_type(self, type_name):
        """Converte il nome interno del tipo in un nome visualizzabile"""
        type_names = {
            'power_supplies': 'Alimentatori',
            'dataloggers': 'Datalogger', 
            'oscilloscopes': 'Oscilloscopi',
            'electronic_loads': 'Carichi Elettronici'
        }
        return type_names.get(type_name, type_name.replace('_', ' ').title())

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
        """Mostra i dettagli di un tipo di strumento"""
        series_list = self.load_instruments.get_series(type_key) or []
        total_models = sum(len(series.get('models', [])) for series in series_list)
        
        details = f"""TIPO DI STRUMENTO: {self.get_display_name_for_type(type_key)}
        
Numero di serie: {len(series_list) if series_list else 0}
Numero totale di modelli: {total_models}

Serie disponibili:
"""
        for series in series_list:
            series_name = series.get('series_name', 'Serie senza nome')
            model_count = len(series.get('models', []))
            details += f"• {series_name} ({model_count} modelli)\n"
            
        self.details_text.setPlainText(details)

    def show_series_details(self, series_data):
        """Mostra i dettagli di una serie"""
        series_name = series_data.get('series_name', 'Serie senza nome')
        series_id = series_data.get('series_id', 'N/A')
        models = series_data.get('models', [])
        
        details = f"""SERIE: {series_name}
        
ID Serie: {series_id}
Numero di modelli: {len(models)}

Comandi SCPI comuni:
"""
        
        common_commands = series_data.get('common_scpi_commands', {})
        for cmd_name, cmd_value in common_commands.items():
            details += f"• {cmd_name}: {cmd_value}\n"
            
        if models:
            details += f"\nModelli nella serie:\n"
            for model in models:
                model_name = model.get('name', 'Modello senza nome')
                capabilities = model.get('capabilities', {})
                channels = capabilities.get('number_of_channels', 'N/A')
                details += f"• {model_name} ({channels} canali)\n"
                
        self.details_text.setPlainText(details)

    def show_model_details(self, model_data):
        """Mostra i dettagli completi di un modello"""
        name = model_data.get('name', 'Modello senza nome')
        manufacturer = model_data.get('manufacturer', 'N/A')
        model_id = model_data.get('id', 'N/A')
        
        details = f"""MODELLO: {name}
        
Produttore: {manufacturer}
ID Modello: {model_id}
Documentazione: {model_data.get('documentation_path', 'N/A')}

"""
        
        # Capabilities
        capabilities = model_data.get('capabilities', {})
        if capabilities:
            details += "CARATTERISTICHE:\n"
            num_channels = capabilities.get('number_of_channels', 'N/A')
            details += f"• Numero di canali: {num_channels}\n"
            
            if 'read_voltage' in capabilities:
                details += f"• Lettura tensione: {'Sì' if capabilities['read_voltage'] else 'No'}\n"
            if 'read_current' in capabilities:
                details += f"• Lettura corrente: {'Sì' if capabilities['read_current'] else 'No'}\n"
                
            # Dettagli canali
            channels = capabilities.get('channels', [])
            number_of_channels = capabilities.get('number_of_channels', 0)
            
            # Gestisce sia il caso di lista che di numero intero
            if isinstance(channels, list) and channels:
                details += f"\nCanali disponibili ({len(channels)}):\n"
                for i, channel in enumerate(channels):
                    if isinstance(channel, dict):
                        ch_id = channel.get('channel_id', f'CH{i+1}')
                        ch_label = channel.get('label', 'N/A')
                        details += f"• {ch_id}: {ch_label}\n"
            elif isinstance(channels, int) and channels > 0:
                details += f"\nNumero di canali: {channels}\n"
            elif number_of_channels > 0:
                details += f"\nNumero di canali: {number_of_channels}\n"
        
        # Interfacce supportate
        interface_info = model_data.get('interface', {})
        connection_types = interface_info.get('supported_connection_types', [])
        if connection_types:
            details += f"\nInterfacce supportate:\n"
            for conn in connection_types:
                conn_type = conn.get('type', 'N/A')
                example = conn.get('address_format_example', 'N/A')
                details += f"• {conn_type}: {example}\n"
        
        # Comandi SCPI specifici
        scpi_commands = model_data.get('scpi_commands', {})
        if scpi_commands:
            details += f"\nComandi SCPI specifici del modello:\n"
            for cmd_name, cmd_value in scpi_commands.items():
                details += f"• {cmd_name}: {cmd_value}\n"
                
        # Note aggiuntive
        notes = model_data.get('notes', '')
        if notes:
            details += f"\nNote:\n{notes}\n"
            
        self.details_text.setPlainText(details)

    def load_instrument_library(self):
        # Usa self.load_instruments per accedere ai dati
        return self.load_instruments

    def save_instrument_library(self):
        # Se serve salvare, usa i metodi di LoadInstruments
        pass