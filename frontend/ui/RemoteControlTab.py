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
        self.channels_layout = QHBoxLayout()  # Cambiato da QVBoxLayout a QHBoxLayout per supportare colonne
        self.channels_container.setLayout(self.channels_layout)
        self.main_layout.addWidget(self.channels_container)
        
        # Crea le colonne per i canali
        self.left_column = QVBoxLayout()
        self.right_column = QVBoxLayout()
        self.channels_layout.addLayout(self.left_column)
        self.channels_layout.addLayout(self.right_column)
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
    
    def diagnose_connection(self, visa_address: str) -> dict:
        """
        Perform diagnostic tests on instrument connection.
        
        Args:
            visa_address: VISA address to diagnose (e.g., 'TCPIP0::192.168.1.100::INSTR')
            
        Returns:
            Dictionary with diagnostic results
        """
        import subprocess
        import re
        
        results = {
            'visa_address': visa_address,
            'address_valid': False,
            'host_reachable': False,
            'port_open': False,
            'visa_available': PYVISA_AVAILABLE,
            'recommendations': []
        }
        
        # Parse VISA address to extract host and port
        try:
            # Pattern for TCPIP: TCPIP[board]::host[:port]::INSTR
            tcpip_pattern = r'TCPIP\d*::([^:]+)(?:::(\d+))?::INSTR'
            match = re.match(tcpip_pattern, visa_address, re.IGNORECASE)
            
            if match:
                results['address_valid'] = True
                host = match.group(1)
                port = match.group(2) if match.group(2) else '111'  # VXI-11 default port
                
                results['host'] = host
                results['port'] = int(port)
                
                # Test 1: Ping host
                try:
                    ping_result = subprocess.run(
                        ['ping', '-c', '1', '-W', '2', host],
                        capture_output=True,
                        text=True,
                        timeout=3
                    )
                    results['host_reachable'] = ping_result.returncode == 0
                    results['ping_output'] = ping_result.stdout
                    
                    if not results['host_reachable']:
                        results['recommendations'].append(
                            f"Host {host} is not reachable. Check network connection and IP address."
                        )
                except subprocess.TimeoutExpired:
                    results['host_reachable'] = False
                    results['recommendations'].append(f"Ping to {host} timed out. Network may be slow or host is blocking ICMP.")
                except Exception as e:
                    results['ping_error'] = str(e)
                    results['recommendations'].append(f"Could not ping host: {str(e)}")
                
                # Test 2: Check if port is open (using netcat or telnet)
                if results['host_reachable']:
                    try:
                        # Try with nc (netcat) first
                        nc_result = subprocess.run(
                            ['nc', '-zv', '-w', '2', host, str(port)],
                            capture_output=True,
                            text=True,
                            timeout=3
                        )
                        results['port_open'] = nc_result.returncode == 0
                        
                        if not results['port_open']:
                            results['recommendations'].append(
                                f"Port {port} on {host} is closed or filtered. "
                                f"Verify VXI-11 service is running on instrument."
                            )
                    except FileNotFoundError:
                        # nc not available, try with timeout command and telnet
                        try:
                            telnet_result = subprocess.run(
                                ['timeout', '2', 'telnet', host, str(port)],
                                capture_output=True,
                                text=True
                            )
                            # If telnet connects, it usually returns 0 or gets timeout
                            results['port_open'] = 'Connected' in telnet_result.stdout or telnet_result.returncode == 124
                        except Exception:
                            results['recommendations'].append(
                                f"Could not test port {port}. Install 'nc' or 'telnet' for better diagnostics."
                            )
                    except Exception as e:
                        results['port_test_error'] = str(e)
            else:
                results['recommendations'].append(
                    f"VISA address format not recognized: {visa_address}\n"
                    f"Expected format: TCPIP0::hostname::INSTR or TCPIP0::hostname::port::INSTR"
                )
                
        except Exception as e:
            results['parse_error'] = str(e)
            results['recommendations'].append(f"Error parsing VISA address: {str(e)}")
        
        # Add general recommendations
        if not results['visa_available']:
            results['recommendations'].append("PyVISA is not available. Install it with: pip install pyvisa pyvisa-py")
        
        if results['address_valid'] and not results['host_reachable']:
            results['recommendations'].append(
                f"Host {host} is not reachable. Check:\n"
                "  - Instrument is powered on\n"
                "  - IP address is correct\n"
                "  - Network cable is connected\n"
                "  - Instrument and PC are on the same network"
            )
        
        if results['address_valid'] and results['host_reachable'] and not results['port_open']:
            results['recommendations'].append(
                f"Port {port} is closed on {host}. Common causes:\n"
                "  VXI-11 Protocol (port 111):\n"
                "    - Use format: TCPIP0::{host}::inst0::INSTR\n"
                "    - Enable VXI-11/LXI service on instrument\n"
                "    - Check firewall settings\n"
                "  HiSLIP Protocol (port 4880):\n"
                "    - Use format: TCPIP0::{host}::hislip0::INSTR\n"
                "    - Enable HiSLIP service on instrument\n"
                "  Socket Protocol (custom port):\n"
                "    - Use format: TCPIP0::{host}::{port}::SOCKET\n"
                "    - Verify correct port number in instrument settings\n"
                "\n"
                "Try changing the protocol in Address Editor if connection fails."
            )
        
        if results['port_open'] and 'inst0' in visa_address.lower():
            results['recommendations'].append(
                "Port is open but connection may still fail. If using VXI-11:\n"
                "  - Ensure RPC portmapper is running on instrument\n"
                "  - Try HiSLIP protocol instead: TCPIP0::{host}::hislip0::INSTR"
            )
            results['recommendations'].append("Check that instrument is powered on and connected to network.")
            results['recommendations'].append("Verify IP address configuration on instrument.")
        
        if results['host_reachable'] and not results['port_open']:
            results['recommendations'].append("Enable remote control/LXI interface on instrument.")
            results['recommendations'].append("Check instrument manual for VXI-11 or SCPI-over-LAN setup.")
            results['recommendations'].append("Verify firewall is not blocking the connection.")
        
        return results
    
    def show_connection_diagnostics(self, visa_address: str):
        """
        Show connection diagnostics dialog with detailed troubleshooting information.
        
        Args:
            visa_address: VISA address to diagnose
        """
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QTextEdit, QPushButton, QProgressBar
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Connection Diagnostics - {visa_address}")
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
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.close)
        layout.addWidget(close_btn)
        
        dialog.show()
        
        # Run diagnostics in background (simulated with QTimer to avoid blocking UI)
        def run_diagnostics():
            progress.setVisible(False)
            results = self.diagnose_connection(visa_address)
            
            # Format results
            output = f"Connection Diagnostics for: {visa_address}\n"
            output += "=" * 60 + "\n\n"
            
            output += f"✓ VISA Available: {'Yes' if results['visa_available'] else 'No'}\n"
            output += f"{'✓' if results['address_valid'] else '✗'} Address Valid: {'Yes' if results['address_valid'] else 'No'}\n"
            
            if 'host' in results:
                output += f"\nHost: {results['host']}\n"
                output += f"Port: {results['port']}\n\n"
                output += f"{'✓' if results['host_reachable'] else '✗'} Host Reachable: {'Yes' if results['host_reachable'] else 'No'}\n"
                output += f"{'✓' if results['port_open'] else '✗'} Port Open: {'Yes' if results['port_open'] else 'No'}\n"
            
            if results['recommendations']:
                output += "\n" + "=" * 60 + "\n"
                output += "RECOMMENDATIONS:\n"
                output += "=" * 60 + "\n\n"
                for i, rec in enumerate(results['recommendations'], 1):
                    output += f"{i}. {rec}\n\n"
            
            if 'ping_output' in results:
                output += "\n" + "=" * 60 + "\n"
                output += "PING OUTPUT:\n"
                output += "=" * 60 + "\n"
                output += results['ping_output']
            
            text_area.setText(output)
            
            # Log diagnostics
            if self.logger:
                self.logger.info(f"Connection diagnostics completed for {visa_address}")
                self.logger.debug(f"Diagnostics results: {results}")
        
    def _show_connection_error_with_diagnostics(self, error_message, visa_address):
        """
        Show connection error with option to run diagnostics.
        
        Args:
            error_message: The error message to display
            visa_address: The VISA address that failed to connect
        """
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Connection Error")
        dialog.setMinimumWidth(500)
        
        layout = QVBoxLayout()
        
        # Error icon and title
        title_layout = QHBoxLayout()
        title_label = QLabel("❌ Connection Failed")
        title_label.setStyleSheet("font-size: 14pt; font-weight: bold; color: #d32f2f;")
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
        
        diagnose_btn = QPushButton("🔍 Run Diagnostics")
        diagnose_btn.clicked.connect(lambda: [dialog.accept(), self.show_connection_diagnostics(visa_address)])
        diagnose_btn.setStyleSheet("background-color: #1976d2; color: white; padding: 8px;")
        
        close_btn = QPushButton("Close")
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
            if action == 'output_on':
                return 'OUTP ON'
            if action == 'output_off':
                return 'OUTP OFF'
            return ''
        # Mappa azione → chiave SCPI
        action_map = {
            'set_voltage': ['set_voltage', 'VOLT'],
            'set_current': ['set_current', 'CURR'],
            'read_voltage': ['read_voltage', 'MEAS:VOLT?'],
            'read_current': ['read_current', 'MEAS:CURR?'],
            'read_measurement': ['read_measurement', 'MEAS?'],
            'output_on': ['output_on', 'OUTP ON'],
            'output_off': ['output_off', 'OUTP OFF']
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
            # Clear previous controls - pulisci colonne
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
            
            # Pulisci la terza colonna se esiste
            if hasattr(self, 'third_column'):
                for i in reversed(range(self.third_column.count())):
                    item = self.third_column.itemAt(i)
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
            
            print(f"\n=== DEBUG: Analisi strumenti per layout ottimizzato ===")
            print(f"Strumenti validi: {len(power_instruments)}")
            print(f"Totale canali abilitati: {total_enabled_channels}")
            
            # Ordina gli strumenti dal più grande al più piccolo per un miglior bilanciamento
            power_instruments.sort(key=lambda x: x['channel_count'], reverse=True)
            
            for i, inst_info in enumerate(power_instruments):
                inst_name = inst_info['inst'].get('instance_name', 'N/A')
                channel_count = inst_info['channel_count']
                print(f"  -> Strumento ordinato [{i}]: {inst_name} ({channel_count} canali)")
            
            # Determina il numero di colonne necessarie
            if total_enabled_channels <= 4:
                num_columns = 1
            elif 5 <= total_enabled_channels <= 8:
                num_columns = 2
            else:
                num_columns = 3
            
            # Crea colonne aggiuntive se necessarie
            if num_columns >= 3 and not hasattr(self, 'third_column'):
                self.third_column = QVBoxLayout()
                self.channels_layout.addLayout(self.third_column)
            
            print(f"Layout scelto: {num_columns} colonne per {total_enabled_channels} canali totali")
            
            # --- Then, for each power supply/electronic load, create a group per instrument ---
            print("\n=== DEBUG: Creazione controlli alimentatori/carichi ===")
            columns = [self.left_column, self.right_column]
            if num_columns >= 3:
                columns.append(self.third_column)
            
            # Azzera le colonne prima di aggiungere nuovi widget
            for col in columns:
                while col.count():
                    item = col.takeAt(0)
                    widget = item.widget()
                    if widget:
                        widget.setParent(None)
            
            # Distribuisci gli strumenti nelle colonne in modo bilanciato
            column_loads = [0] * num_columns  # Conta canali per colonna
            for inst_info in power_instruments:
                inst = inst_info['inst']
                enabled_channels = inst_info['enabled_channels']
                channel_count = inst_info['channel_count']
                
                print(f"Elaborazione strumento: {inst.get('instance_name', 'N/A')} - {channel_count} canali")
                
                # --- Pulsante di connessione per strumento ---
                conn_btn = QPushButton(f"Connect {inst.get('instance_name','')}")
                conn_btn.setCheckable(True)
                conn_btn.setStyleSheet('QPushButton { font-weight: bold; padding: 5px; }')
                def try_connect(inst, btn):
                    visa_addr = inst.get('visa_address', '')
                    if not visa_addr:
                        btn.setStyleSheet('border: 2px solid orange;')
                        btn.setChecked(False)
                        return
                    try:
                        if not self._ensure_visa_initialized():
                            btn.setStyleSheet('border: 2px solid red;')
                            btn.setChecked(False)
                            return
                        instr = self.rm.open_resource(visa_addr)
                        self.visa_connections[visa_addr] = instr
                        btn.setStyleSheet('border: 2px solid green;')
                        btn.setChecked(True)
                    except ConnectionRefusedError as e:
                        btn.setStyleSheet('border: 2px solid red;')
                        btn.setChecked(False)
                        
                        # Specific error for connection refused with diagnostics option
                        error_msg = f"Connection refused to {visa_addr}\n\n"
                        error_msg += "Possible causes:\n"
                        error_msg += "• Instrument is powered off\n"
                        error_msg += "• Wrong IP address or port\n"
                        error_msg += "• VXI-11 service not running on instrument\n"
                        error_msg += "• Network/firewall blocking connection\n"
                        error_msg += f"\nTechnical details: {str(e)}"
                        
                        # Show error with diagnostics option
                        self._show_connection_error_with_diagnostics(error_msg, visa_addr)
                        
                        # Safe timer management
                        timer_key = f"{inst.get('instance_name', 'unknown')}_{id(btn)}"
                        if timer_key in self.connection_timers:
                            self.connection_timers[timer_key].stop()
                            self.connection_timers[timer_key].deleteLater()
                        
                        timer = QTimer(self)
                        timer.setSingleShot(True)
                        timer.timeout.connect(lambda: self.safe_retry_connection(inst, btn, timer_key))
                    except TimeoutError as e:
                        btn.setStyleSheet('border: 2px solid red;')
                        btn.setChecked(False)
                        
                        # Specific error for timeout
                        error_msg = f"Connection timeout to {visa_addr}\n\n"
                        error_msg += "Possible causes:\n"
                        error_msg += "• Instrument is not responding\n"
                        error_msg += "• Network latency too high\n"
                        error_msg += "• Instrument is busy with another operation\n"
                        error_msg += f"\nTechnical details: {str(e)}"
                        
                        self.error_handler.handle_visa_error(
                            Exception(error_msg), 
                            f"connection to {visa_addr}"
                        )
                        
                        # Safe timer management
                        timer_key = f"{inst.get('instance_name', 'unknown')}_{id(btn)}"
                        if timer_key in self.connection_timers:
                            self.connection_timers[timer_key].stop()
                            self.connection_timers[timer_key].deleteLater()
                        
                        timer = QTimer(self)
                        timer.setSingleShot(True)
                        timer.timeout.connect(lambda: self.safe_retry_connection(inst, btn, timer_key))
                    except Exception as e:
                        btn.setStyleSheet('border: 2px solid red;')
                        btn.setChecked(False)
                        
                        # Generic error with detailed message
                        error_type = type(e).__name__
                        error_msg = f"Failed to connect to {visa_addr}\n\n"
                        error_msg += f"Error type: {error_type}\n"
                        error_msg += f"Details: {str(e)}\n\n"
                        error_msg += "Troubleshooting steps:\n"
                        error_msg += "1. Verify instrument is powered on\n"
                        error_msg += "2. Check VISA address is correct\n"
                        error_msg += "3. Test network connectivity (ping)\n"
                        error_msg += "4. Verify VISA backend is installed\n"
                        error_msg += "5. Check instrument manual for remote control setup"
                        
                        # Log error using centralized error handler
                        self.error_handler.handle_visa_error(
                            Exception(error_msg), 
                            f"connection to {visa_addr}"
                        )
                        
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
                
                # Strategia di layout per strumento con molti canali (>3)
                if channel_count > 3:
                    # Crea sotto-colonne per questo strumento
                    print(f"  → Strumento con {channel_count} canali: creazione sotto-colonne")
                    inst_main_group = QGroupBox(f"{inst.get('instance_name','')} ({inst.get('model','')})")
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
                    
                    # Trova la colonna con meno carico per questo strumento grande
                    best_column_idx = column_loads.index(min(column_loads))
                    columns[best_column_idx].addWidget(inst_main_group)
                    column_loads[best_column_idx] += channel_count
                    
                    print(f"  ✓ Strumento con sotto-colonne aggiunto alla colonna {best_column_idx + 1}")
                    
                else:
                    # Strumento normale: crea groupbox standard
                    inst_group = QGroupBox(f"{inst.get('instance_name','')} ({inst.get('model','')})")
                    inst_vbox = QVBoxLayout()
                    inst_vbox.addWidget(conn_btn)
                    
                    # Aggiungi tutti i canali abilitati
                    for ch in enabled_channels:
                        channel_widget = self._create_channel_widget(inst, ch)
                        inst_vbox.addWidget(channel_widget)
                        self.current_channel_widgets.append(channel_widget)
                    
                    inst_group.setLayout(inst_vbox)
                    
                    # Trova la colonna con meno carico
                    best_column_idx = column_loads.index(min(column_loads))
                    columns[best_column_idx].addWidget(inst_group)
                    column_loads[best_column_idx] += channel_count
                    
                    print(f"  ✓ Strumento aggiunto alla colonna {best_column_idx + 1} (carico: {column_loads[best_column_idx]})")
            
            print(f"\n=== Distribuzione finale ===")
            for i, load in enumerate(column_loads):
                print(f"Colonna {i+1}: {load} canali")
            print(f"Totale widget canali creati: {len(self.current_channel_widgets)}")
            print("=" * 50 + "\n")
            
            # Aggiungi stretch alle colonne per allineamento in alto
            for column in columns:
                column.addStretch()
            
        except Exception as e:
            error_msg = f"ERRORE in load_instruments: {str(e)}\nTraceback: {traceback.format_exc()}"
            print(error_msg)
            if self.logger:
                self.logger.error(error_msg)
            # Error already logged - no popup needed
    
    def _create_channel_widget(self, inst, ch):
        """
        Crea un widget per un singolo canale di strumento.
        :param inst: Dati dello strumento
        :param ch: Dati del canale
        :return: QGroupBox contenente i controlli del canale
        """
        print(f"      → Creazione controlli per canale {ch.get('name', 'N/A')}")
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
        
        # Output button and Read button on the same row
        hbox_controls = QHBoxLayout()
        
        # Output enable/disable button
        output_btn = QPushButton('Output: OFF')
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
        
        # Add a read actual values button
        read_btn = QPushButton('Read Values')
        hbox_controls.addWidget(read_btn)
        
        vbox.addLayout(hbox_controls)
        
        # Label for read values
        read_lbl = QLabel('V: ...  I: ...')
        read_btn.clicked.connect(lambda _, i=inst, c=ch, l=read_lbl: self.read_actual(i, c, l))
        vbox.addWidget(read_lbl)
        
        group.setLayout(vbox)
        print(f"    ✓ Widget creato per canale {ch.get('name', 'N/A')}")
        return group

    def get_visa_instrument(self, inst):
        """
        Get the VISA instrument object for the given instance.
        Opens a new connection if not already open.
        :param inst: Instrument instance data.
        :return: VISA instrument object or None if error.
        """
        print(f"[DEBUG] get_visa_instrument chiamato per {inst.get('instance_name', 'N/A')}")
        
        if not self._ensure_visa_initialized():
            print("[DEBUG] VISA non inizializzato!")
            return None
            
        visa_addr = inst.get('visa_address', None)
        print(f"[DEBUG] VISA address: {visa_addr}")
        
        if not visa_addr:
            print("[DEBUG] VISA address mancante!")
            return None
            
        if visa_addr in self.visa_connections:
            print(f"[DEBUG] Connessione esistente trovata per {visa_addr}")
            return self.visa_connections[visa_addr]
            
        print(f"[DEBUG] Tentativo apertura nuova connessione a {visa_addr}")
        try:
            instr = self.rm.open_resource(visa_addr)
            self.visa_connections[visa_addr] = instr
            print(f"[DEBUG] Connessione aperta con successo: {instr}")
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
        print(f"[DEBUG] set_voltage chiamato per {inst.get('instance_name', 'N/A')}")
        
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
        
        print(f"[DEBUG] Valore validato: {value_float}V")
        
        instr = self.get_visa_instrument(inst)
        if not instr:
            print(f"[DEBUG] ERRORE: get_visa_instrument ha restituito None!")
            return
        
        print(f"[DEBUG] Strumento VISA ottenuto: {instr}")
        
        try:
            cmd = self.get_scpi_cmd(inst, ch, 'set_voltage').replace('{value}', value_str)
            print(f"[DEBUG] Comando SCPI: '{cmd}'")
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
        print(f"[DEBUG] set_current chiamato per {inst.get('instance_name', 'N/A')}")
        
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
        
        print(f"[DEBUG] Valore validato: {value_float}A")
        
        instr = self.get_visa_instrument(inst)
        if not instr:
            print(f"[DEBUG] ERRORE: get_visa_instrument ha restituito None!")
            return
        
        print(f"[DEBUG] Strumento VISA ottenuto: {instr}")
        
        try:
            cmd = self.get_scpi_cmd(inst, ch, 'set_current').replace('{value}', value_str)
            print(f"[DEBUG] Comando SCPI: '{cmd}'")
            instr.write(cmd)
            print(f"[RemoteControlTab] Corrente impostata: {value_float}A per {inst.get('instance_name', 'N/A')}")
        except Exception as e:
            error_msg = f'Set Current Error: {str(e)}'
            print(f"ERRORE: {error_msg}")
            if self.logger:
                self.logger.error(error_msg)

    def toggle_output(self, inst, ch, button, checked):
        """
        Enable or disable the output for the given instrument and channel.
        :param inst: Instrument instance data.
        :param ch: Channel data.
        :param button: QPushButton that was clicked.
        :param checked: Boolean state of the button (True=ON, False=OFF).
        """
        print(f"[DEBUG] toggle_output chiamato - Checked: {checked}")
        
        instr = self.get_visa_instrument(inst)
        if not instr:
            print(f"[DEBUG] ERRORE: get_visa_instrument ha restituito None!")
            # Reset button state if connection failed
            button.setChecked(False)
            button.setText('Output: OFF')
            return
        
        print(f"[DEBUG] Strumento VISA ottenuto: {instr}")
        
        try:
            if checked:
                # Turn output ON
                cmd = self.get_scpi_cmd(inst, ch, 'output_on')
                print(f"[DEBUG] Comando ON: '{cmd}'")
                instr.write(cmd)
                button.setText('Output: ON')
                print(f"[RemoteControlTab] Output abilitato per {inst.get('instance_name', 'N/A')} - {ch.get('name', 'N/A')}")
            else:
                # Turn output OFF
                cmd = self.get_scpi_cmd(inst, ch, 'output_off')
                print(f"[DEBUG] Comando OFF: '{cmd}'")
                instr.write(cmd)
                button.setText('Output: OFF')
                print(f"[RemoteControlTab] Output disabilitato per {inst.get('instance_name', 'N/A')} - {ch.get('name', 'N/A')}")
                
        except Exception as e:
            error_msg = f'Toggle Output Error: {str(e)}'
            print(f"ERRORE: {error_msg}")
            if self.logger:
                self.logger.error(error_msg)
            # Reset button to previous state on error
            button.setChecked(not checked)
            button.setText('Output: ON' if not checked else 'Output: OFF')

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
