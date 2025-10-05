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
    On top, a single box shows all measurements from dataloggers/multimeters.
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
        self.label = QLabel('Remote control of instruments')
        self.main_layout.addWidget(self.label)
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
        self.meas_group.setTitle(translator.t('measurements') if hasattr(translator, 't') else 'Measurements (Datalogger/Multimeter)')
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
            
            # --- First, collect all datalogger/multimeter/oscilloscope channels for measurement area ---
            self.meas_vars = []  # [(inst, ch)]
            for inst in inst_data.get('instruments', []):
                if inst.get('instrument_type') in ['dataloggers', 'multimeters']:
                    for ch in inst.get('channels', []):
                        if ch.get('enabled', True):  # Solo canali abilitati
                            self.meas_vars.append((inst, ch))
                # Aggiungi anche i canali degli oscilloscopi abilitati
                elif inst.get('instrument_type') == 'oscilloscopes':
                    for ch in inst.get('channels', []):
                        if ch.get('enabled', False):  # Solo canali esplicitamente abilitati
                            self.meas_vars.append((inst, ch))
            
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
                        unit = ch.get('unit_of_measure', 'V')  # Default V se non specificato
                    
                    # Crea etichetta con formato: Nome_variabile = --- unità
                    label = QLabel(f"{var_name} = --- {unit}")
                    label.setStyleSheet("""
                        QLabel {
                            border: 1px solid #ccc;
                            padding: 8px;
                            margin: 2px;
                            background-color: #f9f9f9;
                            border-radius: 4px;
                            font-family: 'Courier New', monospace;
                            font-size: 12px;
                            min-width: 150px;
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
                if inst.get('instrument_type') in ['power_supplies', 'electronic_loads']:
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
                    # Per ogni canale, aggiungi i controlli
                    print(f"  Iterazione canali per {inst.get('instance_name', 'N/A')}:")
                    for ch_idx, ch in enumerate(inst.get('channels', [])):
                        print(f"    Canale [{ch_idx}]: {ch.get('name', 'N/A')} - Enabled: {ch.get('enabled', 'N/A')}")
                        group = QGroupBox(f"{inst.get('instance_name','')} - {ch.get('name','')}")
                        group.setProperty('instrument', inst)
                        group.setProperty('channel', ch)
                        vbox = QVBoxLayout()
                        # Voltage set
                        hbox_v = QHBoxLayout()
                        hbox_v.addWidget(QLabel('Voltage (V):'))
                        v_edit = QLineEdit()
                        v_edit.setPlaceholderText('Set voltage')
                        set_v_btn = QPushButton('Set')
                        set_v_btn.clicked.connect(lambda _, i=inst, c=ch, e=v_edit: self.set_voltage(i, c, e))
                        hbox_v.addWidget(v_edit)
                        hbox_v.addWidget(set_v_btn)
                        vbox.addLayout(hbox_v)
                        # Current set
                        hbox_c = QHBoxLayout()
                        hbox_c.addWidget(QLabel('Current (A):'))
                        c_edit = QLineEdit()
                        c_edit.setPlaceholderText('Set current')
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
        value = edit.text()
        instr = self.get_visa_instrument(inst)
        if not instr:
            return
        try:
            cmd = self.get_scpi_cmd(inst, ch, 'set_voltage').replace('{value}', value)
            instr.write(cmd)
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
        value = edit.text()
        instr = self.get_visa_instrument(inst)
        if not instr:
            return
        try:
            cmd = self.get_scpi_cmd(inst, ch, 'set_current').replace('{value}', value)
            instr.write(cmd)
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
            unit = ch.get('unit_of_measure', 'V')
            attenuation = ch.get('attenuation', 1.0)  # Default nessuna attenuazione
            
            label = self.meas_labels.get((inst.get('instance_name',''), var_name))
            if not label:
                continue
                
            if not instr:
                # Strumento non connesso
                label.setText(f"{var_name} = NC {unit}")
                label.setStyleSheet(label.styleSheet().replace('background-color: #f9f9f9', 'background-color: #ffeeee'))
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
                    label.setStyleSheet(label.styleSheet().replace('background-color: #ffeeee', 'background-color: #f9f9f9'))
                    
                except ValueError:
                    # Il valore non è numerico, mostra così com'è
                    clean_val = raw_val.strip()
                    label.setText(f"{var_name} = {clean_val} {unit}")
                    
            except Exception as e:
                label.setText(f"{var_name} = ERR {unit}")
                label.setStyleSheet(label.styleSheet().replace('background-color: #f9f9f9', 'background-color: #ffeeee'))
    
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
