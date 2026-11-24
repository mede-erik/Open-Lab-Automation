# Copyright (C) 2025-2026 Erik Medeossi
# This file is part of Open Lab Automation.
# Licensed under the GNU General Public License v3.0; see the LICENSE file.

import json
import logging
import os

from ola.library import Library as _Library
from ola.library import load_schemas as _load_schemas
from ola.library import resolve_model_commands as _resolve_model_commands

logger = logging.getLogger('frontend.core.LoadInstruments')


def get_library_path():
    """Absolute path of Instruments_LIB/instruments_lib.json (repository root)."""
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(repo_root, 'Instruments_LIB', 'instruments_lib.json')


class LoadInstruments:
    """
    Classe per la gestione e l'accesso agli strumenti caricati da file JSON.
    Permette di recuperare strumenti per id, nome, tipo e di accedere a parametri specifici come canali, capabilities e comandi SCPI.
    """
    def __init__(self):
        """Inizializza la lista strumenti vuota."""
        self.instruments = {}
        self.library_path = None
        self._ola_library = None

    def load_instruments(self, file_path=None):
        """
        Loads the instrument list from a JSON file.
        Args:
            file_path (str): Path to the instruments JSON file (default: repository library).
        Returns:
            bool: True if the library was loaded and has a valid structure.
        """
        file_path = file_path or get_library_path()
        self.library_path = file_path
        self._ola_library = None
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except FileNotFoundError:
            logger.error(f"File not found: {file_path} "
                         f"(is the Instruments_LIB submodule initialised? "
                         f"run: git submodule update --init)")
            self.instruments = {}
            return False
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.error(f"Error decoding JSON from file: {file_path}")
            self.instruments = {}
            return False
        except OSError as e:
            logger.error(f"Cannot read instrument library {file_path}: {e}")
            self.instruments = {}
            return False

        # Normalize to dictionary with 'instrument_library' key
        if isinstance(data, dict) and 'instrument_library' in data:
            data = data['instrument_library']
        if not isinstance(data, dict) or not any(k.endswith('_series') for k in data):
            logger.error(f"Invalid instrument library structure in {file_path}")
            self.instruments = {}
            return False
        self.instruments = data
        return True

    @staticmethod
    def get_series_key(type_name):
        """
        Restituisce la chiave della libreria (pluralizzata) per un tipo di strumento.
        Args:
            type_name (str): Tipo di strumento (es. 'power_supply', 'datalogger',
                             'oscilloscope', 'electronic_load', 'switch_unit', 'network_analyzer',
                             'function_generator', 'multimeter', 'rf_signal_generator',
                             'spectrum_analyzer').
        Returns:
            str | None: Chiave della libreria (es. 'power_supplies_series') o None.
        """
        key_by_type = {
            'power_supply': 'power_supplies_series',
            'datalogger': 'dataloggers_series',
            'oscilloscope': 'oscilloscopes_series',
            'electronic_load': 'electronic_loads_series',
            'switch_unit': 'switch_units_series',
            'network_analyzer': 'network_analyzers_series',
            'function_generator': 'function_generators_series',
            'multimeter': 'multimeters_series',
            'rf_signal_generator': 'rf_signal_generators_series',
            'spectrum_analyzer': 'spectrum_analyzers_series',
        }
        return key_by_type.get(type_name)

    def get_series(self, type_name):
        """
        Recupera tutte le serie disponibili per un tipo di strumento specifico.
        Args:
            type_name (str): Tipo di strumento (es. 'power_supply', 'datalogger', 'oscilloscope', 'electronic_load').
        Returns:
            list | None: Lista delle serie disponibili per il tipo di strumento specificato.
        """
        key = self.get_series_key(type_name)
        if not key:
            return None
        return self.instruments.get(key)

    def get_models(self, type_name, series_id):
        """
        Recupera tutti i modelli per una serie e tipo specifici.
        Args:
            type_name (str): Tipo di strumento (es. 'power_supply', 'datalogger', 'oscilloscope', 'electronic_load').
            series_id (str): ID della serie di strumenti.
        Returns:
            list | None: Lista dei modelli disponibili per la serie e il tipo specificati.
        """
        series_list = self.get_series(type_name) or []
        for series in series_list:
            if series.get('series_id') == series_id:
                return series.get('models')
        return None

    def get_visible_models(self, type_name, series_id, include_experimental=False):
        """
        Recupera i modelli visibili (non sperimentali per default) per una serie.
        Args:
            type_name (str): Tipo di strumento.
            series_id (str): ID della serie di strumenti.
            include_experimental (bool): Se True, include anche i modelli sperimentali.
        Returns:
            list | None: Lista dei modelli filtrati.
        """
        models = self.get_models(type_name, series_id)
        if not models:
            return None
        
        if include_experimental:
            return models
        
        visible_models = []
        for model in models:
            if not model.get('experimental', False):
                visible_models.append(model)
        return visible_models

    def get_visible_series(self, type_name, include_experimental=False):
        """
        Recupera tutte le serie visibili (non sperimentali per default) per un tipo.
        Args:
            type_name (str): Tipo di strumento.
            include_experimental (bool): Se True, include anche le serie con modelli sperimentali.
        Returns:
            list | None: Lista delle serie con modelli visibili.
        """
        series_list = self.get_series(type_name) or []
        if include_experimental:
            return series_list
        
        visible_series = []
        for series in series_list:
            models = series.get('models', [])
            visible_models = [m for m in models if not m.get('experimental', False)]
            if visible_models:
                visible_series.append({**series, 'models': visible_models})
        return visible_series if visible_series else None

    def get_model_capabilities(self, type_name, series_id, model_id):
        """
        Recupera le capabilities di un modello specifico.
        Args:
            type_name (str): Tipo di strumento (es. 'power_supply', 'datalogger', 'oscilloscope', 'electronic_load').
            series_id (str): ID della serie di strumenti.
            model_id (str): ID del modello di strumenti.
        Returns:
            dict | None: Dizionario contenente le capabilities del modello specificato.
        """
        series_list = self.get_series(type_name) or []
        for series in series_list:
            if series.get('series_id') == series_id:
                for model in series.get('models', []):
                    if model.get('id') == model_id:
                        return model.get('capabilities')
        return None

    def get_model_scpi(self, type_name, series_id, model_id):
        """
        Recupera i comandi SCPI (comuni e specifici) per un modello.
        Args:
            type_name (str): Tipo di strumento (es. 'power_supply', 'datalogger').
            series_id (str): ID della serie di strumenti.
            model_id (str): ID del modello di strumenti.
        Returns:
            dict: Dizionario contenente i comandi SCPI del modello specificato.
        """
        series_list = self.get_series(type_name) or []
        for series in series_list:
            if series.get('series_id') == series_id:
                for model in series.get('models', []):
                    if model.get('id') == model_id:
                        return self.resolve_model_commands(series, model)
        return None

    def get_library(self):
        """
        Return the Qt-free ola.library.Library built from the loaded instruments and the
        call schemas found in the 'schema' folder next to the library file.
        Returns:
            ola.library.Library: library used by the call planner.
        """
        if self._ola_library is None:
            schemas = {}
            if self.library_path:
                schema_dir = os.path.join(os.path.dirname(os.path.abspath(self.library_path)), 'schema')
                if os.path.isdir(schema_dir):
                    schemas = _load_schemas(schema_dir)
            self._ola_library = _Library(self.instruments, schemas)
        return self._ola_library

    @staticmethod
    def resolve_model_commands(series, model):
        """
        Build the SCPI command set of one model from its series (override, remove with null,
        patch). Thin wrapper: the logic lives in the Qt-free module ola.library.
        Args:
            series (dict): Series dict from the library.
            model (dict): Model dict belonging to the series.
        Returns:
            dict: Call name -> command definition for this model.
        """
        return _resolve_model_commands(series, model)

    def get_supported_connections(self, type_name, series_id, model_id):
        """
        Recupera i tipi di connessione supportati dal modello.
        Args:
            type_name (str): Tipo di strumento (es. 'power_supply', 'datalogger').
            series_id (str): ID della serie di strumenti.
            model_id (str): ID del modello di strumenti.
        Returns:
            list: Lista dei tipi di connessione supportati dal modello specificato.
        """
        series_list = self.get_series(type_name) or []
        for series in series_list:
            if series.get('series_id') == series_id:
                for model in series.get('models', []):
                    if model.get('id') == model_id:
                        interface = model.get('interface', {})
                        return interface.get('supported_connection_types')
        return None

    def get_channel_info(self, type_name, series_id, model_id):
        """
        Recupera info dettagliate su tutti i canali (id, limiti, nomi, ecc.) di un modello specifico.
        Args:
            type_name (str): Tipo di strumento (es. 'power_supply', 'datalogger').
            series_id (str): ID della serie di strumenti.
            model_id (str): ID del modello di strumenti.
        Returns:
            list: Lista di dizionari contenenti info dettagliate sui canali del modello specificato.
        """
        series_list = self.get_series(type_name) or []
        for series in series_list:
            if series.get('series_id') == series_id:
                for model in series.get('models', []):
                    if model.get('id') == model_id:
                        channels = model.get('channels')
                        if not channels:
                            channels = model.get('capabilities', {}).get('channels')
                        return channels or None
        return None

    def get_channel_ids(self, type_name, series_id, model_id):
        """
        Restituisce la lista degli ID dei canali di un modello.
        Supporta il nuovo formato 'capabilities.channels[].channel_id' e i legacy
        ('channel_ids', 'capabilities.channel_ids'). Fallback: CH1..CHn.
        Args:
            type_name (str): Tipo di strumento (es. 'power_supply').
            series_id (str): ID della serie di strumenti.
            model_id (str): ID del modello di strumenti.
        Returns:
            list: Lista di ID canali (es. ['1', '2', '3']).
        """
        caps = self.get_model_capabilities(type_name, series_id, model_id) or {}
        channels = caps.get('channels') if isinstance(caps.get('channels'), list) else None
        if channels:
            return [ch.get('channel_id', f'CH{i+1}') for i, ch in enumerate(channels)]
        channel_ids = caps.get('channel_ids')
        if isinstance(channel_ids, list) and channel_ids:
            return list(channel_ids)
        num = caps.get('number_of_channels', caps.get('number_of_slots', 0))
        if isinstance(num, list):
            num = len(num)
        ids = [f'CH{i+1}' for i in range(int(num or 0))]
        if not ids and type_name == 'electronic_load':
            # Single-input electronic loads may omit any channel definition
            ids = ['CH1']
        return ids

    def get_channel_limits(self, type_name, series_id, model_id, channel_id=None):
        """
        Restituisce i limiti elettrici di un modello (o di un singolo canale).
        Cerca prima in 'capabilities.channels[]', poi nei campi flat
        ('max_current_a', 'max_voltage_v', 'max_power_w').
        Args:
            type_name (str): Tipo di strumento (es. 'power_supply').
            series_id (str): ID della serie di strumenti.
            model_id (str): ID del modello di strumenti.
            channel_id (str): ID del canale (opzionale).
        Returns:
            dict: {'max_current': float|None, 'max_voltage': float|None, 'max_power': float|None}.
        """
        caps = self.get_model_capabilities(type_name, series_id, model_id) or {}
        limits = {
            'max_current': caps.get('max_current_a'),
            'max_voltage': caps.get('max_voltage_v'),
            'max_power': caps.get('max_power_w'),
        }
        channels = caps.get('channels') if isinstance(caps.get('channels'), list) else None
        if channels:
            channel = None
            if channel_id is not None:
                channel = next(
                    (ch for ch in channels
                     if str(ch.get('channel_id')) == str(channel_id)),
                    None
                )
            if channel is None:
                # Senza channel_id specifico usa il primo canale come default
                # (valido anche per strumenti multi-canale omogenei).
                channel = channels[0]
            vout = channel.get('voltage_output') or {}
            cout = channel.get('current_output') or {}
            limits['max_current'] = cout.get('max', limits['max_current'])
            limits['max_voltage'] = vout.get('max', limits['max_voltage'])
        return limits

    def find_instrument(self, type_name=None, series_id=None, model_id=None):
        """
        Ricerca avanzata per trovare uno strumento dato tipo, serie, modello.
        Args:
            type_name (str): Tipo di strumento (es. 'power_supply', 'datalogger').
            series_id (str): ID della serie di strumenti.
            model_id (str): ID del modello di strumenti.
        Returns:
            dict: Dizionario contenente le informazioni sullo strumento trovato.
        """
        series_list = self.get_series(type_name) or []
        for series in series_list:
            if series_id and series.get('series_id') == series_id:
                for model in series.get('models', []):
                    if model_id and model.get('id') == model_id:
                        return model
                return series
        return None

    @staticmethod
    def _norm_model(text):
        """A model name compared without case, spaces, dashes and underscores."""
        return ''.join(ch for ch in str(text or '').upper() if ch.isalnum())

    def find_models_by_idn(self, idn_text):
        """The library models an ``*IDN?`` answer (``manufacturer,model,serial,firmware``) names.

        Returns a list of ``(type_name, series_id, model)`` (``model`` is the library entry), the
        best first: the model field must match the ``model`` of the entry (case, spaces and dashes
        do not count); when several do, the ones whose manufacturer shares a word with the answer
        come first. Experimental models are included. Empty list if nothing matches."""
        parts = [p.strip() for p in str(idn_text or '').split(',')]
        if len(parts) < 2 or not self._norm_model(parts[1]):
            return []
        wanted = self._norm_model(parts[1])
        maker_words = {w for w in parts[0].upper().replace('-', ' ').split() if len(w) > 1}
        found = []
        for type_name in self.get_all_types():
            for series in self.get_series(type_name) or []:
                for model in series.get('models', []) or []:
                    if self._norm_model(model.get('model')) != wanted:
                        continue
                    words = set(str(model.get('manufacturer', '')).upper().replace('-', ' ').split())
                    found.append((not (maker_words & words), type_name, series.get('series_id'), model))
        found.sort(key=lambda item: item[0])
        return [(t, s, m) for _, t, s, m in found]

    def get_all_types(self):
        """
        Restituisce tutti i tipi di strumenti disponibili nella libreria.
        Rileva i tipi in base alle chiavi presenti nel file libreria.
        Returns:
            list: Lista dei tipi di strumenti disponibili.
        """
        mapping = [
            ('power_supplies_series', 'power_supply'),
            ('dataloggers_series', 'datalogger'),
            ('oscilloscopes_series', 'oscilloscope'),
            ('electronic_loads_series', 'electronic_load'),
            ('switch_units_series', 'switch_unit'),
            ('network_analyzers_series', 'network_analyzer'),
            ('function_generators_series', 'function_generator'),
            ('multimeters_series', 'multimeter'),
            ('rf_signal_generators_series', 'rf_signal_generator'),
            ('spectrum_analyzers_series', 'spectrum_analyzer'),
        ]
        available = []
        for key, tname in mapping:
            series = self.instruments.get(key)
            if isinstance(series, list) and len(series) > 0:
                available.append(tname)
        # Assicura che tutte le categorie siano disponibili nella GUI di aggiunta
        # anche quando la libreria non contiene ancora serie per quel tipo.
        all_types = [tname for _, tname in mapping]
        for tname in all_types:
            if tname not in available:
                available.append(tname)
        return available

    def get_series_name(self, type_name, series_id):
        """
        Restituisce il nome leggibile di una serie dato il suo id.
        Args:
            type_name (str): Tipo di strumento (es. 'power_supply', 'datalogger').
            series_id (str): ID della serie di strumenti.
        Returns:
            str: Nome leggibile della serie.
        """
        series_list = self.get_series(type_name) or []
        for series in series_list:
            if series.get('series_id') == series_id:
                return series.get('series_name')
        return None

    def get_model_name(self, type_name, series_id, model_id):
        """
        Restituisce il nome leggibile di un modello dato il suo id.
        Args:
            type_name (str): Tipo di strumento (es. 'power_supply', 'datalogger').
            series_id (str): ID della serie di strumenti.
            model_id (str): ID del modello di strumenti.
        Returns:
            str: Nome leggibile del modello.
        """
        series_list = self.get_series(type_name) or []
        for series in series_list:
            if series.get('series_id') == series_id:
                for model in series.get('models', []):
                    if model.get('id') == model_id:
                        return model.get('name')
        return None

    def get_all_datalogger_modules(self):
        """
        Restituisce tutti i moduli datalogger disponibili nella libreria.
        Returns:
            list: Lista di dizionari contenenti le informazioni sui moduli datalogger.
        """
        return self.instruments.get('datalogger_modules', [])

    def get_module_info(self, module_id):
        """
        Restituisce le informazioni di un modulo datalogger specifico.
        Args:
            module_id (str): ID del modulo (es. '34901A', '34902A').
        Returns:
            dict: Dizionario con le informazioni del modulo o None se non trovato.
        """
        modules = self.get_all_datalogger_modules()
        for module in modules:
            if module.get('id') == module_id:
                return module
        return None

    def get_module_channels(self, module_id):
        """
        Restituisce il numero di canali di un modulo datalogger specifico.
        Args:
            module_id (str): ID del modulo (es. '34901A', '34902A').
        Returns:
            int: Numero di canali del modulo, o 0 se non trovato.
        """
        module = self.get_module_info(module_id)
        if not module:
            return 0
        capabilities = module.get('capabilities', {})
        channels = capabilities.get('number_of_channels', 0)
        if isinstance(channels, list):
            return len(channels)
        return int(channels or 0)

    def get_compatible_modules(self, type_name, series_id, model_id):
        """
        Restituisce i moduli compatibili per un datalogger specifico.
        Args:
            type_name (str): Tipo di strumento (deve essere 'datalogger').
            series_id (str): ID della serie del datalogger.
            model_id (str): ID del modello del datalogger.
        Returns:
            list: Lista di module_id compatibili, o lista vuota se non ci sono moduli.
        """
        if type_name != 'datalogger':
            return []
        
        capabilities = self.get_model_capabilities(type_name, series_id, model_id)
        if not capabilities:
            return []
        
        return capabilities.get('compatible_modules', [])

    def get_enabled_compatible_modules(self, type_name, series_id, model_id):
        """
        Restituisce solo i moduli compatibili e abilitati per un datalogger.
        Args:
            type_name (str): Tipo di strumento (deve essere 'datalogger').
            series_id (str): ID della serie del datalogger.
            model_id (str): ID del modello del datalogger.
        Returns:
            list: Lista di dizionari con le informazioni dei moduli abilitati e compatibili.
        """
        compatible_ids = self.get_compatible_modules(type_name, series_id, model_id)
        all_modules = self.get_all_datalogger_modules()
        
        enabled_modules = []
        for module in all_modules:
            module_id = module.get('id', module.get('module_id'))
            # Controlla se il modulo è nella lista dei compatibili e non è disabilitato
            if module_id in compatible_ids and not module.get('not_enabled', False):
                enabled_modules.append(module)
        
        return enabled_modules
