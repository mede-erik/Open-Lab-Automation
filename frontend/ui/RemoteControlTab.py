import os
import json
import traceback
try:
    import pyvisa
    PYVISA_AVAILABLE = True
except (ImportError, ValueError) as e:
    pyvisa = None
    PYVISA_AVAILABLE = False
    print(f"PyVISA non disponibile: {e}")
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QGroupBox, QLineEdit, QPushButton, QHBoxLayout, QCheckBox, QSlider
from PyQt6.QtCore import QTimer, Qt
from frontend.core.LoadInstruments import LoadInstruments
from frontend.core.errorhandler import ErrorHandler, VISAError, UIError, ErrorCode


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
    def __init__(self, load_instruments):
        """
        Initialize the RemoteControlTab.
        Sets up the layout, measurement group, and channels container.
        """
        super().__init__()
        self.instruments_manager = load_instruments  # Rinominato per evitare conflitti
        
        # Initialize logger and error handler
        try:
            from core.logger import Logger
            self.logger = Logger()
            self.logger.info("RemoteControlTab initialization started")
        except Exception as e:
            print(f"Impossibile inizializzare logger: {e}")
            self.logger = None
            
        # Initialize error handler
        self.error_handler = ErrorHandler()
            
        if self.instruments_manager is None:
            msg = "ATTENZIONE: RemoteControlTab inizializzato senza LoadInstruments"
            print(msg)
            if self.logger:
                self.logger.error(msg)
        else:
            msg = f"RemoteControlTab inizializzato con LoadInstruments: {type(self.instruments_manager)}"
            print(msg)
            if self.logger:
                self.logger.info(msg)
                
        self.main_layout = QVBoxLayout()
        # Layout orizzontale per titolo e pulsante reload
        top_layout = QHBoxLayout()
        self.label = QLabel('Remote control of instruments')
        top_layout.addWidget(self.label)
        # Pulsante oscilloscopio con icona
        self.osc_btn = QPushButton()
        self.osc_btn.setToolTip('Configura Oscilloscopio (.was)')
        osc_icon_path = os.path.join(os.path.dirname(__file__), '../assets/icons/oscilloscope.png')
        print(f"[RemoteControlTab] Cercando icona oscilloscopio: {osc_icon_path}")
        if os.path.exists(osc_icon_path):
            from PyQt6.QtGui import QIcon
            from PyQt6.QtCore import QSize
            icon = QIcon(osc_icon_path)
            self.osc_btn.setIcon(icon)
            self.osc_btn.setIconSize(QSize(48, 48))  # Icona 48px dentro pulsante 64px
            print(f"[RemoteControlTab] Icona oscilloscopio caricata: {osc_icon_path}")
        else:
            self.osc_btn.setText('OSC')
            print(f"[RemoteControlTab] Icona oscilloscopio non trovata, usando testo")
        self.osc_btn.setFixedSize(64, 64)
        self.osc_btn.clicked.connect(self._configure_oscilloscope_from_was)
        top_layout.addWidget(self.osc_btn)
        # Pulsante reload con icona
        self.reload_btn = QPushButton()
        self.reload_btn.setToolTip('Ricarica strumenti (.inst)')
        refresh_icon_path = os.path.join(os.path.dirname(__file__), '../assets/icons/refresh.png')
        print(f"[RemoteControlTab] Cercando icona refresh: {refresh_icon_path}")
        if os.path.exists(refresh_icon_path):
            from PyQt6.QtGui import QIcon
            from PyQt6.QtCore import QSize
            icon = QIcon(refresh_icon_path)
            self.reload_btn.setIcon(icon)
            self.reload_btn.setIconSize(QSize(48, 48))  # Icona 48px dentro pulsante 64px
            print(f"[RemoteControlTab] Icona refresh caricata: {refresh_icon_path}")
        else:
            self.reload_btn.setText('↻')
            print(f"[RemoteControlTab] Icona refresh non trovata, usando testo")
        self.reload_btn.setFixedSize(64, 64)
        self.reload_btn.clicked.connect(self._reload_instruments_from_mainwindow)
        top_layout.addWidget(self.reload_btn)
        top_layout.addStretch()
        self.main_layout.addLayout(top_layout)
        self.meas_group = QGroupBox('Measurements (Datalogger/Multimeter)')
        self.meas_layout = QVBoxLayout()
        self.meas_group.setLayout(self.meas_layout)
        self.main_layout.addWidget(self.meas_group)
        self.channels_container = QWidget()
        self.channels_layout = QVBoxLayout()
        self.channels_container.setLayout(self.channels_layout)
        self.main_layout.addWidget(self.channels_container)
        self.main_layout.addStretch()
        self.setLayout(self.main_layout)
        self.current_channel_widgets = []  # Stores references to current channel widgets
        # Initialize VISA resource manager with lazy loading to avoid segmentation fault
        self.rm = None
        self._visa_init_attempted = False
        self.visa_connections = {}  # Stores active VISA connections
        self.meas_labels = {}  # Stores measurement labels for dataloggers
        self.connection_timers = {}  # Stores connection retry timers

    def _reload_instruments_from_mainwindow(self):
        """Richiama la funzione di reload strumenti dal MainWindow se disponibile."""
        parent = self.parent()
        # Cerca il MainWindow nella gerarchia
        while parent is not None and not hasattr(parent, 'reload_remote_tab_instruments'):
            parent = parent.parent()
        if parent is not None and hasattr(parent, 'reload_remote_tab_instruments'):
            parent.reload_remote_tab_instruments()
        else:
            print("[RemoteControlTab] MainWindow con reload_remote_tab_instruments non trovato.")
    
    def _configure_oscilloscope_from_was(self):
        """Configura l'oscilloscopio con i parametri dal file .was del progetto corrente."""
        parent = self.parent()
        # Cerca il MainWindow nella gerarchia
        while parent is not None and not hasattr(parent, 'current_project_dir'):
            parent = parent.parent()
        
        if parent is None or not hasattr(parent, 'current_project_data'):
            print("[RemoteControlTab] MainWindow non trovato o progetto non caricato.")
            return
        
        if not parent.current_project_dir or not parent.current_project_data:
            print("[RemoteControlTab] Nessun progetto attivo.")
            return
        
        # Trova il primo file .was nel progetto
        was_files = parent.current_project_data.get('was_files', [])
        if not was_files:
            print("[RemoteControlTab] Nessun file .was trovato nel progetto.")
            return
        
        was_file = was_files[0]  # Usa il primo file .was
        was_path = os.path.join(parent.current_project_dir, was_file)
        
        if not os.path.exists(was_path):
            print(f"[RemoteControlTab] File .was non trovato: {was_path}")
            return
        
        try:
            # Carica i parametri dal file .was
            with open(was_path, 'r', encoding='utf-8') as f:
                was_data = json.load(f)
            
            print(f"[RemoteControlTab] Configurazione oscilloscopio da: {was_file}")
            print(f"[RemoteControlTab] Parametri caricati: {list(was_data.keys())}")
            
            # Qui puoi implementare la logica per inviare i comandi SCPI all'oscilloscopio
            # Esempio: configurazione timebase, canali, trigger, ecc.
            self._apply_oscilloscope_settings(was_data)
            
        except Exception as e:
            print(f"[RemoteControlTab] Errore durante caricamento file .was: {e}")
    
    def _apply_oscilloscope_settings(self, was_data):
        """Applica le impostazioni dell'oscilloscopio tramite comandi SCPI."""
        # Trova gli oscilloscopi negli strumenti caricati
        if not hasattr(self, 'visa_connections'):
            print("[RemoteControlTab] Nessuna connessione VISA attiva.")
            return
        
        # Carica gli oscilloscopi dal file .inst del progetto corrente
        oscilloscopes = self._get_project_oscilloscopes()
        if not oscilloscopes:
            print("[RemoteControlTab] Nessun oscilloscopio trovato nel progetto.")
            return
        
        print(f"[RemoteControlTab] Trovati {len(oscilloscopes)} oscilloscopi nel progetto.")
        
        for osc_inst in oscilloscopes:
            try:
                self._configure_single_oscilloscope(osc_inst, was_data)
            except Exception as e:
                print(f"[RemoteControlTab] Errore configurazione oscilloscopio {osc_inst.get('instance_name', 'N/A')}: {e}")
        
        print("[RemoteControlTab] Configurazione oscilloscopi completata.")
    
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
            print(f"[RemoteControlTab] Analisi strumenti nel file .inst:")
            for idx, inst in enumerate(inst_data.get('instruments', [])):
                inst_type = inst.get('instrument_type', '')
                inst_name = inst.get('instance_name', 'N/A')
                print(f"  [{idx}] {inst_name} - Tipo: '{inst_type}'")
                
                # Gestisce sia 'oscilloscope' che 'oscilloscopes'
                if inst_type in ['oscilloscope', 'oscilloscopes']:
                    oscilloscopes.append(inst)
                    print(f"    → Oscilloscopio trovato: {inst_name}")
            
            print(f"[RemoteControlTab] Oscilloscopi trovati: {len(oscilloscopes)}")
            return oscilloscopes
        except Exception as e:
            print(f"[RemoteControlTab] Errore lettura file .inst: {e}")
            return []
    
    def _configure_single_oscilloscope(self, osc_inst, was_data):
        """Configura un singolo oscilloscopio con i parametri dal file .was."""
        osc_name = osc_inst.get('instance_name', 'N/A')
        osc_model = osc_inst.get('model', '')
        visa_addr = osc_inst.get('visa_address', '')
        
        print(f"[RemoteControlTab] Configurazione oscilloscopio: {osc_name} ({osc_model})")
        
        if not visa_addr:
            print(f"[RemoteControlTab] Indirizzo VISA mancante per {osc_name}")
            return
        
        # Carica i comandi SCPI specifici per questo modello dalla libreria
        scpi_commands = self._get_oscilloscope_scpi_commands(osc_model)
        if not scpi_commands:
            print(f"[RemoteControlTab] Comandi SCPI non trovati per modello {osc_model}")
            return
        
        # Connessione VISA
        if not self._ensure_visa_initialized():
            print(f"[RemoteControlTab] VISA non inizializzato")
            return
        
        try:
            # Connetti all'oscilloscopio
            if visa_addr in self.visa_connections:
                instr = self.visa_connections[visa_addr]
            else:
                instr = self.rm.open_resource(visa_addr)
                self.visa_connections[visa_addr] = instr
            
            print(f"[RemoteControlTab] Connesso a {osc_name} su {visa_addr}")
            
            # Applica le impostazioni dal file .was
            self._apply_was_settings_to_oscilloscope(instr, scpi_commands, was_data)
            
        except Exception as e:
            print(f"[RemoteControlTab] Errore connessione a {osc_name}: {e}")
    
    def _get_oscilloscope_scpi_commands(self, model_id):
        """Recupera i comandi SCPI per il modello di oscilloscopio dalla libreria."""
        if not self.instruments_manager:
            return {}
        
        try:
            # Cerca nelle serie di oscilloscopi
            osc_series = self.instruments_manager.instruments.get('oscilloscopes_series', [])
            
            for series in osc_series:
                for model in series.get('models', []):
                    if model.get('id') == model_id or model.get('model') == model_id:
                        # Combina comandi comuni della serie con quelli specifici del modello
                        common_commands = series.get('common_scpi_commands', {})
                        model_commands = model.get('scpi_commands', {})
                        
                        # Merge dei comandi
                        combined_commands = {**common_commands, **model_commands}
                        print(f"[RemoteControlTab] Trovati {len(combined_commands)} comandi SCPI per {model_id}")
                        return combined_commands
            
            print(f"[RemoteControlTab] Modello {model_id} non trovato nella libreria")
            return {}
            
        except Exception as e:
            print(f"[RemoteControlTab] Errore recupero comandi SCPI: {e}")
            return {}
    
    def _apply_was_settings_to_oscilloscope(self, instr, scpi_commands, was_data):
        """Applica le impostazioni specifiche del file .was all'oscilloscopio."""
        try:
            # Reset oscilloscopio
            if 'reset' in scpi_commands:
                instr.write(scpi_commands['reset'])
                print("[RemoteControlTab] Reset oscilloscopio")
            
            # Applica impostazioni timebase
            if 'timebase_scale' in was_data and 'set_timebase_scale' in scpi_commands:
                timebase_value = was_data['timebase_scale']
                cmd = scpi_commands['set_timebase_scale'].format(value=timebase_value)
                instr.write(cmd)
                print(f"[RemoteControlTab] Timebase: {timebase_value}")
            
            # Applica impostazioni canali
            channels = was_data.get('channels', {})
            for ch_num, ch_settings in channels.items():
                channel_number = ch_num.replace('CH', '').replace('CHAN', '')
                
                # Scala canale
                if 'scale' in ch_settings and 'set_channel_scale' in scpi_commands:
                    scale_value = ch_settings['scale']
                    cmd = scpi_commands['set_channel_scale'].format(channel_number=channel_number, value=scale_value)
                    instr.write(cmd)
                    print(f"[RemoteControlTab] Canale {channel_number} scala: {scale_value}")
                
                # Offset canale
                if 'offset' in ch_settings and 'set_channel_offset' in scpi_commands:
                    offset_value = ch_settings['offset']
                    cmd = scpi_commands['set_channel_offset'].format(channel_number=channel_number, value=offset_value)
                    instr.write(cmd)
                    print(f"[RemoteControlTab] Canale {channel_number} offset: {offset_value}")
                
                # Accoppiamento canale
                if 'coupling' in ch_settings and 'set_channel_coupling' in scpi_commands:
                    coupling_value = ch_settings['coupling']
                    cmd = scpi_commands['set_channel_coupling'].format(channel_number=channel_number, coupling_type=coupling_value)
                    instr.write(cmd)
                    print(f"[RemoteControlTab] Canale {channel_number} coupling: {coupling_value}")
            
            # Applica impostazioni trigger
            trigger = was_data.get('trigger', {})
            if trigger:
                # Sorgente trigger
                if 'source' in trigger and 'set_trigger_source' in scpi_commands:
                    source = trigger['source']
                    # Estrai numero canale da stringhe come 'CH1', 'CHAN1'
                    if source.upper().startswith(('CH', 'CHAN')):
                        channel_number = source.replace('CH', '').replace('CHAN', '').replace('ch', '').replace('chan', '')
                        cmd = scpi_commands['set_trigger_source'].format(channel_number=channel_number)
                        instr.write(cmd)
                        print(f"[RemoteControlTab] Trigger source: {source}")
                
                # Livello trigger
                if 'level' in trigger and 'set_trigger_level' in scpi_commands:
                    level_value = trigger['level']
                    cmd = scpi_commands['set_trigger_level'].format(value=level_value)
                    instr.write(cmd)
                    print(f"[RemoteControlTab] Trigger level: {level_value}")
                
                # Modalità trigger
                if 'mode' in trigger and 'set_trigger_mode' in scpi_commands:
                    mode_value = trigger['mode']
                    cmd = scpi_commands['set_trigger_mode'].format(mode=mode_value)
                    instr.write(cmd)
                    print(f"[RemoteControlTab] Trigger mode: {mode_value}")
            
            # Auto setup se disponibile
            if 'auto_setup' in scpi_commands:
                instr.write(scpi_commands['auto_setup'])
                print("[RemoteControlTab] Auto setup eseguito")
            
            print(f"[RemoteControlTab] Configurazione completata con successo")
            
        except Exception as e:
            print(f"[RemoteControlTab] Errore durante applicazione impostazioni: {e}")
        self.setLayout(self.main_layout)
        self.current_channel_widgets = []  # Stores references to current channel widgets
        # Initialize VISA resource manager with lazy loading to avoid segmentation fault
        self.rm = None
        self._visa_init_attempted = False
        
        if PYVISA_AVAILABLE and pyvisa is not None:
            print("PyVISA disponibile - inizializzazione VISA rimandata al primo utilizzo")
        else:
            print("PyVISA non disponibile - controllo strumenti disabilitato")
        
        self.visa_connections = {}  # Stores active VISA connections
        self.meas_labels = {}  # Stores measurement labels for dataloggers
        self.connection_timers = {}  # Stores connection retry timers

    def _ensure_visa_initialized(self):
        """
        Inizializza il VISA resource manager solo quando necessario (lazy loading).
        Questo evita segmentation fault durante l'avvio dell'applicazione.
        """
        if self._visa_init_attempted:
            return self.rm is not None
            
        self._visa_init_attempted = True
        
        if not PYVISA_AVAILABLE or pyvisa is None:
            print("PyVISA non disponibile")
            return False
            
        try:
            print("Inizializzazione lazy del VISA resource manager...")
            # Prova prima con backend sicuro @py
            try:
                self.rm = pyvisa.ResourceManager('@py')
                print("✓ VISA resource manager inizializzato con backend @py")
                return True
            except Exception as e:
                print(f"Backend @py fallito: {e}")
                # Fallback al backend di default
                try:
                    self.rm = pyvisa.ResourceManager()
                    print("✓ VISA resource manager inizializzato con backend di default")
                    return True
                except Exception as e2:
                    print(f"Backend di default fallito: {e2}")
                    
        except Exception as e:
            print(f"✗ Errore inizializzazione VISA: {e}")
            
        self.rm = None
        print("Controllo strumenti disabilitato - problemi con PyVISA")
        return False

    def safe_retry_connection(self, inst, btn, timer_key):
        """
        Metodo sicuro per ritentare la connessione che verifica se il button esiste ancora.
        """
        try:
            # Verifica se il button è ancora valido
            if btn is None or not hasattr(btn, 'setStyleSheet'):
                # Il button è stato eliminato, rimuovi il timer
                if timer_key in self.connection_timers:
                    self.connection_timers[timer_key].stop()
                    del self.connection_timers[timer_key]
                return
            
            # Prova a connetterti di nuovo
            if not self._ensure_visa_initialized():
                btn.setStyleSheet('border: 2px solid orange;')
                btn.setChecked(False)
                btn.setToolTip("VISA non disponibile")
                return
                
            visa_addr = inst.get('visa_address', None)
            if not visa_addr:
                btn.setStyleSheet('border: 2px solid red;')
                btn.setChecked(False)
                return
                
            try:
                instr = self.rm.open_resource(visa_addr)
                self.visa_connections[visa_addr] = instr
                btn.setStyleSheet('border: 2px solid green;')
                btn.setChecked(True)
                # Connessione riuscita, rimuovi il timer
                if timer_key in self.connection_timers:
                    self.connection_timers[timer_key].stop()
                    del self.connection_timers[timer_key]
            except Exception as e:
                btn.setStyleSheet('border: 2px solid red;')
                btn.setChecked(False)
                # Log error using centralized error handler (no dialog for retry attempts)
                self.error_handler.handle_visa_error(e, f"retry connection to {visa_addr}")
                # Mantieni il timer per riprovare
                    
        except Exception as e:
            # Gestisci qualsiasi errore inaspettato, inclusi crash UI
            try:
                # Usa il sistema di gestione errori centralizzato
                if "wrapped C/C++ object" in str(e) and "has been deleted" in str(e):
                    self.error_handler.handle_ui_error(e, "retry connection timer")
                else:
                    self.error_handler.handle_error(e, "Unexpected error in connection retry", show_dialog=False)
            except:
                # Fallback se anche l'error handler fallisce
                if self.logger:
                    self.logger.error(f"Errore in safe_retry_connection: {e}")
                else:
                    print(f"Errore in safe_retry_connection: {e}")
                    
            # Rimuovi il timer in caso di errore grave
            if timer_key in self.connection_timers:
                try:
                    self.connection_timers[timer_key].stop()
                    del self.connection_timers[timer_key]
                except:
                    pass

    def get_scpi_cmd(self, inst, ch, action):
        """
        Get the SCPI command for the given instrument/channel/action from the library.
        action: 'set_voltage', 'set_current', 'read_voltage', 'read_current', 'read_measurement'
        """
        type_name = inst.get('instrument_type', '')
        series_id = inst.get('series', '')
        model_id = inst.get('model_id', inst.get('model', ''))
        
        # Check if instruments_manager is available
        if self.instruments_manager is None:
            scpi_dict = None
        else:
            try:
                scpi_dict = self.instruments_manager.get_model_scpi(type_name, series_id, model_id)
            except Exception as e:
                if self.logger:
                    self.logger.error(f"Errore get_model_scpi: {str(e)}")
                scpi_dict = None
        if not scpi_dict:
            # Fallback standard
            if action == 'set_voltage':
                return 'VOLT {value}'
            if action == 'set_current':
                return 'CURR {value}'
            if action == 'read_voltage':
                return 'MEAS:VOLT?'
            if action == 'read_current':
                return 'MEAS:CURR?'
            if action == 'read_measurement':
                return 'MEAS?'
            return ''
        # Mappa azione → chiave SCPI
        action_map = {
            'set_voltage': ['set_voltage', 'VOLT'],
            'set_current': ['set_current', 'CURR'],
            'read_voltage': ['read_voltage', 'MEAS:VOLT?'],
            'read_current': ['read_current', 'MEAS:CURR?'],
            'read_measurement': ['read_measurement', 'MEAS?']
        }
        for key in action_map.get(action, []):
            if key in scpi_dict:
                return scpi_dict[key]
        # Fallback
        return ''

    def update_translation(self, translator):
        """
        Update UI elements with translated text.
        :param translator: Translator instance for language translation.
        """
        self.label.setText(translator.t('remote_control'))
        self.meas_group.setTitle(translator.t('measurements') if hasattr(translator, 't') else 'Measurements (Datalogger/Multimeter only)')
        # Optionally update channel group titles
        for group in self.current_channel_widgets:
            inst = group.property('instrument')
            ch = group.property('channel')
            if inst and ch:
                group.setTitle(f"{inst.get('instance_name', '')} - {ch.get('name', '')}")

    def load_instruments(self, inst_file_path):
        """
        Load instruments from the specified .inst file and create corresponding UI controls.
        :param inst_file_path: Path to the .inst file to load.
        """
        msg = f"load_instruments chiamato con path: {inst_file_path}"
        print(msg)
        if self.logger:
            self.logger.info(msg)
            
        try:
            # Clear previous controls
            for i in reversed(range(self.channels_layout.count())):
                widget = self.channels_layout.itemAt(i).widget()
                if widget:
                    widget.setParent(None)
            self.current_channel_widgets.clear()
            # Clear measurement area
            for i in reversed(range(self.meas_layout.count())):
                widget = self.meas_layout.itemAt(i).widget()
                if widget:
                    widget.setParent(None)
            
            # Stop measurement timer if exists
            if hasattr(self, 'measurement_timer'):
                self.measurement_timer.stop()
                
            # Clear connection timers to prevent crashes
            for timer_key, timer in self.connection_timers.items():
                try:
                    timer.stop()
                    timer.deleteLater()
                except:
                    pass
            self.connection_timers.clear()
                
            self.meas_labels.clear()
            # Close previous VISA connections
            for inst in self.visa_connections.values():
                try:
                    inst.close()
                except Exception:
                    pass
            self.visa_connections = {}
            if not inst_file_path or not os.path.isfile(inst_file_path):
                return
            
            with open(inst_file_path, 'r', encoding='utf-8') as f:
                inst_data = json.load(f)
            
            # DEBUG: Stampa tutti gli strumenti caricati
            print(f"\n=== DEBUG: Strumenti caricati da {inst_file_path} ===")
            for idx, inst in enumerate(inst_data.get('instruments', [])):
                print(f"  [{idx}] {inst.get('instance_name', 'N/A')} - Tipo: {inst.get('instrument_type', 'N/A')}")
                print(f"       Canali: {len(inst.get('channels', []))}")
                for ch_idx, ch in enumerate(inst.get('channels', [])):
                    print(f"         [{ch_idx}] {ch.get('name', 'N/A')} - Enabled: {ch.get('enabled', False)}")
            print("=" * 50 + "\n")
            
            # --- First, collect all datalogger/multimeter channels for measurement area ---
            # Note: Oscilloscopes are excluded as they cannot perform continuous automatic measurements
            self.meas_vars = []  # [(inst, ch)]
            for inst in inst_data.get('instruments', []):
                inst_type = inst.get('instrument_type', '')
                # Gestisce varianti di naming: datalogger/dataloggers, multimeter/multimeters
                if inst_type in ['datalogger', 'dataloggers', 'multimeter', 'multimeters']:
                    for ch in inst.get('channels', []):
                        is_enabled = ch.get('enabled', True)  # Solo canali abilitati
                        if is_enabled:
                            self.meas_vars.append((inst, ch))
                            print(f"    → Canale misura aggiunto: {inst.get('instance_name', 'N/A')} - {ch.get('name', 'N/A')}")
            
            if self.meas_vars:
                # Crea un layout a griglia per le misure
                from PyQt6.QtWidgets import QGridLayout
                meas_grid = QGridLayout()
                
                row = 0
                col = 0
                max_cols = 4  # Massimo 4 misure per riga
                
                for inst, ch in self.meas_vars:
                    # Per oscilloscopi, usa il nome del canale direttamente
                    if inst.get('instrument_type') == 'oscilloscopes':
                        var_name = ch.get('name', ch.get('channel_id', 'Unknown'))
                        unit = 'V'  # Gli oscilloscopi misurano sempre tensioni
                    else:
                        var_name = ch.get('measured_variable', ch.get('name', 'Unknown'))
                        # Per multimetri e datalogger usa l'unità specifica dal canale
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
                    
                    meas_grid.addWidget(label, row, col)
                    self.meas_labels[(inst.get('instance_name',''), var_name)] = label
                    
                    col += 1
                    if col >= max_cols:
                        col = 0
                        row += 1
                
                # Crea un widget contenitore per la griglia
                meas_widget = QWidget()
                meas_widget.setLayout(meas_grid)
                self.meas_layout.addWidget(meas_widget)
                
                # Add control buttons in horizontal layout
                control_layout = QHBoxLayout()
                
                refresh_btn = QPushButton('Aggiorna Misure')
                refresh_btn.clicked.connect(self.refresh_measurements_manual)
                control_layout.addWidget(refresh_btn)
                
                # Toggle per aggiornamento automatico
                self.auto_refresh_cb = QCheckBox('Aggiornamento Automatico')
                self.auto_refresh_cb.setChecked(True)
                self.auto_refresh_cb.toggled.connect(self.toggle_auto_refresh)
                control_layout.addWidget(self.auto_refresh_cb)
                
                # Slider per intervallo di aggiornamento
                interval_label = QLabel('Intervallo (s):')
                control_layout.addWidget(interval_label)
                
                self.interval_slider = QSlider(Qt.Orientation.Horizontal)
                self.interval_slider.setRange(1, 10)  # 1-10 secondi
                self.interval_slider.setValue(2)  # Default 2 secondi
                self.interval_slider.valueChanged.connect(self.update_refresh_interval)
                control_layout.addWidget(self.interval_slider)
                
                self.interval_value_label = QLabel('2s')
                control_layout.addWidget(self.interval_value_label)
                
                control_layout.addStretch()
                
                control_widget = QWidget()
                control_widget.setLayout(control_layout)
                self.meas_layout.addWidget(control_widget)
                
                # Setup timer per aggiornamento automatico
                self.measurement_timer = QTimer()
                self.measurement_timer.timeout.connect(self.refresh_measurements_auto)
                if self.auto_refresh_cb.isChecked():
                    self.measurement_timer.start(2000)  # Start con 2 secondi
                    
            # --- Then, for each power supply/electronic load, create a group per instrument ---
            print("\n=== DEBUG: Creazione controlli alimentatori/carichi ===")
            for inst in inst_data.get('instruments', []):
                print(f"Controllo strumento: {inst.get('instance_name', 'N/A')} - Tipo: {inst.get('instrument_type', 'N/A')}")
                # Gestisce varianti di naming: power_supply/power_supplies, electronic_load/electronic_loads
                inst_type = inst.get('instrument_type', '')
                if inst_type in ['power_supply', 'power_supplies', 'electronic_load', 'electronic_loads']:
                    print(f"  ✓ Tipo valido per controllo remoto")
                    print(f"  Numero canali: {len(inst.get('channels', []))}")
                    visa_addr = inst.get('visa_address', None)
                    print(f"  Indirizzo VISA: {visa_addr}")
                    # --- Pulsante di connessione per strumento ---
                    conn_btn = QPushButton('Collega')
                    conn_btn.setCheckable(True)
                    conn_btn.setChecked(False)
                    conn_btn.setStyleSheet('border: 2px solid gray;')
                    def try_connect(inst=inst, btn=conn_btn):
                        if not self._ensure_visa_initialized():
                            btn.setStyleSheet('border: 2px solid orange;')
                            btn.setChecked(False)
                            btn.setToolTip("VISA non disponibile")
                            return
                            
                        visa_addr = inst.get('visa_address', None)
                        if not visa_addr:
                            btn.setStyleSheet('border: 2px solid red;')
                            btn.setChecked(False)
                            return
                        try:
                            instr = self.rm.open_resource(visa_addr)
                            self.visa_connections[visa_addr] = instr
                            btn.setStyleSheet('border: 2px solid green;')
                            btn.setChecked(True)
                        except Exception as e:
                            btn.setStyleSheet('border: 2px solid red;')
                            btn.setChecked(False)
                            
                            # Log error using centralized error handler
                            self.error_handler.handle_visa_error(e, f"connection to {visa_addr}")
                            
                            # Gestione sicura del timer per evitare crash
                            timer_key = f"{inst.get('instance_name', 'unknown')}_{id(btn)}"
                            if timer_key in self.connection_timers:
                                self.connection_timers[timer_key].stop()
                                self.connection_timers[timer_key].deleteLater()
                            
                            timer = QTimer(self)
                            timer.setSingleShot(True)
                            # Usa una connessione sicura che verifica se il button è ancora valido
                            timer.timeout.connect(lambda: self.safe_retry_connection(inst, btn, timer_key))
                            self.connection_timers[timer_key] = timer
                            timer.start(5000)
                    conn_btn.clicked.connect(lambda _, i=inst, b=conn_btn: try_connect(i, b))
                    # --- Fine pulsante connessione ---
                    # Crea un groupbox per lo strumento
                    inst_group = QGroupBox(f"{inst.get('instance_name','')} ({inst.get('model','')})")
                    inst_vbox = QVBoxLayout()
                    inst_vbox.addWidget(conn_btn)
                    # Per ogni canale, aggiungi i controlli (solo canali abilitati)
                    print(f"  Iterazione canali per {inst.get('instance_name', 'N/A')}:")
                    for ch_idx, ch in enumerate(inst.get('channels', [])):
                        is_enabled = ch.get('enabled', False)
                        print(f"    Canale [{ch_idx}]: {ch.get('name', 'N/A')} - Enabled: {is_enabled}")
                        
                        # Salta canali disabilitati
                        if not is_enabled:
                            print(f"      → Saltato (canale disabilitato)")
                            continue
                            
                        print(f"      → Creazione controlli per canale abilitato")
                        group = QGroupBox(f"{inst.get('instance_name','')} - {ch.get('name','')}")
                        group.setProperty('instrument', inst)
                        group.setProperty('channel', ch)
                        vbox = QVBoxLayout()
                        # Voltage set with limits
                        hbox_v = QHBoxLayout()
                        max_voltage = ch.get('max_voltage', 30.0)  # Valore di default
                        voltage_label = QLabel(f'Voltage (V) [0-{max_voltage}]:')
                        hbox_v.addWidget(voltage_label)
                        v_edit = QLineEdit()
                        v_edit.setPlaceholderText(f'Max: {max_voltage}V')
                        # Validazione input voltaggio
                        from PyQt6.QtGui import QDoubleValidator
                        v_validator = QDoubleValidator(0.0, max_voltage, 3)
                        v_edit.setValidator(v_validator)
                        set_v_btn = QPushButton('Set')
                        set_v_btn.clicked.connect(lambda _, i=inst, c=ch, e=v_edit: self.set_voltage(i, c, e))
                        hbox_v.addWidget(v_edit)
                        hbox_v.addWidget(set_v_btn)
                        vbox.addLayout(hbox_v)
                        # Current set with limits
                        hbox_c = QHBoxLayout()
                        max_current = ch.get('max_current', 10.0)  # Valore di default
                        current_label = QLabel(f'Current (A) [0-{max_current}]:')
                        hbox_c.addWidget(current_label)
                        c_edit = QLineEdit()
                        c_edit.setPlaceholderText(f'Max: {max_current}A')
                        # Validazione input corrente
                        from PyQt6.QtGui import QDoubleValidator
                        c_validator = QDoubleValidator(0.0, max_current, 3)
                        c_edit.setValidator(c_validator)
                        set_c_btn = QPushButton('Set')
                        set_c_btn.clicked.connect(lambda _, i=inst, c=ch, e=c_edit: self.set_current(i, c, e))
                        hbox_c.addWidget(c_edit)
                        hbox_c.addWidget(set_c_btn)
                        vbox.addLayout(hbox_c)
                        # Add a read actual values button
                        read_btn = QPushButton('Read Actual Values')
                        read_lbl = QLabel('V: ...  I: ...')
                        read_btn.clicked.connect(lambda _, i=inst, c=ch, l=read_lbl: self.read_actual(i, c, l))
                        vbox.addWidget(read_btn)
                        vbox.addWidget(read_lbl)
                        group.setLayout(vbox)
                        inst_vbox.addWidget(group)
                        self.current_channel_widgets.append(group)
                        print(f"    ✓ Widget creato per canale {ch.get('name', 'N/A')}")
                    inst_group.setLayout(inst_vbox)
                    self.channels_layout.addWidget(inst_group)
                    print(f"  ✓ GroupBox aggiunto al layout per {inst.get('instance_name', 'N/A')}")
                else:
                    print(f"  ✗ Tipo NON valido per controllo remoto")
            print(f"Totale widget canali creati: {len(self.current_channel_widgets)}")
            print("=" * 50 + "\n")
            self.channels_layout.addStretch()
            
        except Exception as e:
            error_msg = f"ERRORE in load_instruments: {str(e)}\nTraceback: {traceback.format_exc()}"
            print(error_msg)
            if self.logger:
                self.logger.error(error_msg)
            # Error already logged - no popup needed

    def get_visa_instrument(self, inst):
        """
        Get the VISA instrument object for the given instance.
        Opens a new connection if not already open.
        :param inst: Instrument instance data.
        :return: VISA instrument object or None if error.
        """
        if not self._ensure_visa_initialized():
            return None
            
        visa_addr = inst.get('visa_address', None)
        if not visa_addr:
            return None
        if visa_addr in self.visa_connections:
            return self.visa_connections[visa_addr]
        try:
            instr = self.rm.open_resource(visa_addr)
            self.visa_connections[visa_addr] = instr
            return instr
        except Exception as e:
            error_msg = f'Cannot open {visa_addr}: {e}'
            print(f"ERRORE-VISA-002: {error_msg}")
            if self.logger:
                self.logger.error(error_msg, error_code="VISA-002")
            return None

    def set_voltage(self, inst, ch, edit):
        """
        Set the voltage for the given instrument and channel using the SCPI command.
        :param inst: Instrument instance data.
        :param ch: Channel data.
        :param edit: QLineEdit widget containing the voltage value.
        """
        value_str = edit.text().strip()
        if not value_str:
            print("[RemoteControlTab] Valore voltaggio vuoto")
            return
            
        try:
            value_float = float(value_str)
            max_voltage = ch.get('max_voltage', 30.0)
            
            # Validazione limiti
            if value_float < 0:
                print(f"[RemoteControlTab] Voltaggio negativo non consentito: {value_float}V")
                return
            elif value_float > max_voltage:
                print(f"[RemoteControlTab] Voltaggio {value_float}V supera il limite massimo di {max_voltage}V")
                return
                
        except ValueError:
            print(f"[RemoteControlTab] Valore voltaggio non valido: '{value_str}'")
            return
            
        instr = self.get_visa_instrument(inst)
        if not instr:
            return
            
        try:
            cmd = self.get_scpi_cmd(inst, ch, 'set_voltage').replace('{value}', value_str)
            instr.write(cmd)
            print(f"[RemoteControlTab] Voltaggio impostato: {value_float}V per {inst.get('instance_name', 'N/A')}")
        except Exception as e:
            error_msg = f'Set Voltage Error: {str(e)}'
            print(f"ERRORE: {error_msg}")
            if self.logger:
                self.logger.error(error_msg)

    def set_current(self, inst, ch, edit):
        """
        Set the current for the given instrument and channel using the SCPI command.
        :param inst: Instrument instance data.
        :param ch: Channel data.
        :param edit: QLineEdit widget containing the current value.
        """
        value_str = edit.text().strip()
        if not value_str:
            print("[RemoteControlTab] Valore corrente vuoto")
            return
            
        try:
            value_float = float(value_str)
            max_current = ch.get('max_current', 10.0)
            
            # Validazione limiti
            if value_float < 0:
                print(f"[RemoteControlTab] Corrente negativa non consentita: {value_float}A")
                return
            elif value_float > max_current:
                print(f"[RemoteControlTab] Corrente {value_float}A supera il limite massimo di {max_current}A")
                return
                
        except ValueError:
            print(f"[RemoteControlTab] Valore corrente non valido: '{value_str}'")
            return
            
        instr = self.get_visa_instrument(inst)
        if not instr:
            return
            
        try:
            cmd = self.get_scpi_cmd(inst, ch, 'set_current').replace('{value}', value_str)
            instr.write(cmd)
            print(f"[RemoteControlTab] Corrente impostata: {value_float}A per {inst.get('instance_name', 'N/A')}")
        except Exception as e:
            error_msg = f'Set Current Error: {str(e)}'
            print(f"ERRORE: {error_msg}")
            if self.logger:
                self.logger.error(error_msg)

    def read_actual(self, inst, ch, label):
        """
        Read the actual voltage and current values from the instrument and update the label.
        :param inst: Instrument instance data.
        :param ch: Channel data.
        :param label: QLabel widget to update with the read values.
        """
        instr = self.get_visa_instrument(inst)
        if not instr:
            return
        try:
            v_cmd = self.get_scpi_cmd(inst, ch, 'read_voltage')
            c_cmd = self.get_scpi_cmd(inst, ch, 'read_current')
            v = instr.query(v_cmd)
            c = instr.query(c_cmd)
            label.setText(f'V: {v.strip()}  I: {c.strip()}')
        except Exception as e:
            label.setText(f'Error: {e}')

    def refresh_measurements_manual(self):
        """Refresh measurements manually (called by button)."""
        self.refresh_measurements_auto()
    
    def refresh_measurements_auto(self):
        """
        Refresh the measurements displayed in the UI by querying the instruments.
        Nuovo formato: <Nome variabile>=<Valore> <Unità>
        """
        if not hasattr(self, 'meas_vars'):
            return
            
        for inst, ch in self.meas_vars:
            instr = self.get_visa_instrument(inst)
            var_name = ch.get('measured_variable', ch.get('name', 'Unknown'))
            
            # Determina l'unità di misura corretta
            inst_type = inst.get('instrument_type', '')
            if inst_type in ['multimeter', 'multimeters', 'datalogger', 'dataloggers']:
                # Per multimetri e datalogger usa l'unità specifica dal canale
                unit = ch.get('unit', 'V')
                print(f"[DEBUG] {inst_type} - Unità da campo 'unit': {unit} per {var_name}")
            else:
                # Per altri strumenti usa il default o unit_of_measure
                unit = ch.get('unit_of_measure', 'V')
                print(f"[DEBUG] {inst_type} - Unità da 'unit_of_measure': {unit} per {var_name}")
                
            attenuation = ch.get('attenuation', 1.0)  # Default nessuna attenuazione
            
            label = self.meas_labels.get((inst.get('instance_name',''), var_name))
            if not label:
                continue
                
            if not instr:
                # Strumento non connesso
                label.setText(f"{var_name} = NC {unit}")
                label.setProperty("state", "error")
                continue
                
            try:
                cmd = self.get_scpi_cmd(inst, ch, 'read_measurement')
                if not cmd:
                    label.setText(f"{var_name} = N/A {unit}")
                    continue
                    
                raw_val = instr.query(cmd)
                # Pulisce il valore e applica attenuazione
                try:
                    numeric_val = float(raw_val.strip())
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
                    
                except ValueError:
                    # Il valore non è numerico, mostra così com'è
                    clean_val = raw_val.strip()
                    label.setText(f"{var_name} = {clean_val} {unit}")
                    
            except Exception as e:
                label.setText(f"{var_name} = ERR {unit}")
                label.setProperty("state", "error")
    
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
            
            # Pulizia di tutti i timer di connessione
            for timer_key, timer in self.connection_timers.items():
                try:
                    timer.stop()
                    timer.deleteLater()
                except:
                    pass
            self.connection_timers.clear()
            
            # Chiusura di tutte le connessioni VISA
            for addr, instr in self.visa_connections.items():
                try:
                    instr.close()
                except:
                    pass
            self.visa_connections.clear()
            
            if self.logger:
                self.logger.info("RemoteControlTab: Risorse pulite correttamente")
                
        except Exception as e:
            if self.logger:
                self.logger.error(f"Errore durante la pulizia delle risorse: {e}")
            else:
                print(f"Errore durante la pulizia delle risorse: {e}")
        
        # Chiama il metodo padre
        super().closeEvent(a0)
