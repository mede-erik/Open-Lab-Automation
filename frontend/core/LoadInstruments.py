import json 

class LoadInstruments:
    """
    Classe per la gestione e l'accesso agli strumenti caricati da file JSON.
    Permette di recuperare strumenti per id, nome, tipo e di accedere a parametri specifici come canali, capabilities e comandi SCPI.
    """
    def __init__(self):
        """Inizializza la lista strumenti vuota."""
        self.instruments = {}

    def load_instruments(self, file_path):
        """
        Loads the instrument list from a JSON file.
        Args:
            file_path (str): Path to the instruments JSON file.
        """
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                # Normalize to dictionary with 'instrument_library' key
                if isinstance(data, dict) and 'instrument_library' in data:
                    self.instruments = data['instrument_library']
                else:
                    # fallback: accept directly the expected dictionary structure
                    self.instruments = data if isinstance(data, dict) else {}
        except FileNotFoundError:
            print(f"File not found: {file_path}")
        except json.JSONDecodeError:
            print(f"Error decoding JSON from file: {file_path}")

    def get_powersupplys_series(self):
        """
        Retrieves the available power supply series.
        Returns:
            list: List of power supply series.
        """
        # Find instruments of type 'power_supply' and collect their series
        power_supplies_series = self.instruments.get('power_supplies_series', [])
        return power_supplies_series
    
    def get_dataloggers_series(self):
        """
        Retrieves the available datalogger series.
        Returns:
            list: List of datalogger series.
        """
        # Find instruments of type 'datalogger' and collect their series
        dataloggers_series = self.instruments.get('dataloggers_series', [])
        return dataloggers_series

    def get_powersupply_list_id(self):
        """
        Recupera la lista degli ID degli alimentatori disponibili.
        Returns:
            list: Lista degli ID degli alimentatori.
        """
        series_id = []
        power_supplies = self.get_powersupplys_series()
        for series in power_supplies:
            series_id.append(series['series_id'])
        return series_id

    def get_datalogger_list_id(self):
        """
        Recupera la lista degli ID dei datalogger disponibili.
        Returns:
            list: Lista degli ID dei datalogger.
        """
        series_id = []
        dataloggers = self.get_dataloggers_series()
        for series in dataloggers:
            series_id.append(series['series_id'])
        return series_id
    
    def get_powersupply_models(self, series_id):
        """
        Recupera i modelli di alimentatori per una serie specifica.
        Args:
            series_id (str): ID della serie degli alimentatori.
        Returns:
            list: Lista dei modelli di alimentatori per la serie specificata.
        """
        power_supplies = self.get_powersupplys_series()
        for series in power_supplies:
            if series['series_id'] == series_id:
                return series.get('models')
        return None

    def get_datalogger_models(self, series_id):
        """
        Recupera i modelli di datalogger per una serie specifica.
        Args:
            series_id (str): ID della serie dei datalogger.
        Returns:
            list: Lista dei modelli di datalogger per la serie specificata.
        """
        dataloggers = self.get_dataloggers_series()
        for series in dataloggers:
            if series['series_id'] == series_id:
                return series.get('models')
        return None
    
    def get_powersupply_series_name(self, series_id):
        """
        Recupera il nome della serie di alimentatori per un ID specifico.
        Args:
            series_id (str): ID della serie degli alimentatori.
        Returns:
            str: Nome della serie di alimentatori.
        """
        power_supplies = self.get_powersupplys_series()
        for series in power_supplies:
            if series['series_id'] == series_id:
                return series.get('series_name')
        return None

    def get_datalogger_series_name(self, series_id):
        """
        Recupera il nome della serie di datalogger per un ID specifico.
        Args:
            series_id (str): ID della serie dei datalogger.
        Returns:
            str: Nome della serie di datalogger.
        """
        dataloggers = self.get_dataloggers_series()
        for series in dataloggers:
            if series['series_id'] == series_id:
                return series.get('series_name')
        return None

    def get_powersupply_series_name_list(self):
        """
        Recupera la lista dei nomi delle serie di alimentatori disponibili.
        Returns:
            list: Lista dei nomi delle serie di alimentatori.
        """
        power_supplies = self.get_powersupplys_series()
        series_names = [series['series_name'] for series in power_supplies]
        return series_names
    
    def get_datalogger_series_name_list(self):
        """
        Recupera la lista dei nomi delle serie di datalogger disponibili.
        Returns:
            list: Lista dei nomi delle serie di datalogger.
        """
        dataloggers = self.get_dataloggers_series()
        series_names = [series['series_name'] for series in dataloggers]
        return series_names
    
    def get_powersupply_model_name(self, series_id, model_id):
        """
        Recupera il nome del modello di alimentatore per un ID specifico.
        Args:
            model_id (str): ID del modello di alimentatore.
        Returns:
            str: Nome del modello di alimentatore.
        """
        power_supplies = self.get_powersupplys_series()
        for series in power_supplies:
            for model in series['models']:
                if model['id'] == model_id:
                    return model['name']
        return None
    
    def get_datalogger_model_name(self, series_id, model_id):
        """
        Recupera il nome del modello di datalogger per un ID specifico.
        Args:
            model_id (str): ID del modello di datalogger.
        Returns:
            str: Nome del modello di datalogger.
        """
        dataloggers = self.get_dataloggers_series()
        for series in dataloggers:
            for model in series['models']:
                if model['id'] == model_id:
                    return model['name']
        return None

    def get_powersupply_common_scpi(self, series_id):
        """
        Recupera i comandi SCPI comuni per una serie specifica di alimentatori.
        Args:
            series_id (str): ID della serie di alimentatori.
        Returns:
            dict: Dizionario contenente i comandi SCPI comuni per la serie specificata.
        """
        power_supplies = self.get_powersupplys_series()
        for series in power_supplies:
            if series['series_id'] == series_id:
                return series['common_scpi_commands']
        return None
    
    # Note: get_datalogger_common_scpi is already defined above; avoid duplicates

    def get_powersupply_capabilities(self, model_id):
        """
        Recupera le capacità di un modello di alimentatore specifico.
        Args:
            model_id (str): ID del modello di alimentatore.
        Returns:
            dict: Dizionario contenente le capacità del modello di alimentatore specificato.
        """
        power_supplies = self.get_powersupplys_series()
        for series in power_supplies:
            for model in series['models']:
                if model['id'] == model_id:
                    return model['capabilities']
        return None

    def get_powersupply_number_channels(self, model_id):
        """
        Recupera il numero di canali di un modello di alimentatore specifico.
        Args:
            model_id (str): ID del modello di alimentatore.
        Returns:
            int: Numero di canali del modello di alimentatore specificato.
        """
        capabilities = self.get_powersupply_capabilities(model_id)
        if capabilities:
            return capabilities['number_of_channels']
        return None

    def get_powersupply_model_scpi_commands(self, model_id):
        """
        Recupera i comandi SCPI specifici per un modello di alimentatore specifico.
        Args:
            model_id (str): ID del modello di alimentatore.
        Returns:
            dict: Dizionario contenente i comandi SCPI specifici per il modello di alimentatore specificato.
        """
        power_supplies = self.get_powersupplys_series()
        for series in power_supplies:
            for model in series['models']:
                if model['id'] == model_id:
                    return model['scpi_commands']
        return None
    
    def get_powersupply_supported_connection(self, model_id):
        """
        Recupera i tipi di connessione supportati per un modello di alimentatore specifico.
        Args:
            model_id (str): ID del modello di alimentatore.
        Returns:
            list: Lista dei tipi di connessione supportati per il modello di alimentatore specificato.
        """
        power_supplies = self.get_powersupplys_series()
        for series in power_supplies:
            for model in series['models']:
                if model['id'] == model_id:
                    return model['interface']['supported_connection_types']
        return None
    
    def get_powersupply_supported_connection_type_list(self, model_id):
        """
        Recupera l'elenco dei tipi di connessione supportati per un modello di alimentatore specifico.
        Args:
            model_id (str): ID del modello di alimentatore.
        Returns:
            list: Lista dei tipi di connessione supportati per il modello di alimentatore specificato.
        """
        power_supplies = self.get_powersupplys_series()
        for series in power_supplies:
            for model in series['models']:
                if model['id'] == model_id:
                    return [connection['type'] for connection in model['interface']['supported_connection_types']]
        return None
    
    def get_datalogger_common_scpi(self, series_id):
        """
        Recupera i comandi SCPI comuni per una serie specifica di datalogger.
        Args:
            series_id (str): ID della serie di datalogger.
        Returns:
            dict: Dizionario contenente i comandi SCPI comuni per la serie specificata.
        """
        dataloggers = self.get_dataloggers_series()
        for series in dataloggers:
            if series['series_id'] == series_id:
                return series['common_scpi_commands']
        return None

    def get_datalogger_capabilities(self, model_id):
        """
        Recupera le capacità di un modello di datalogger specifico.
        Args:
            model_id (str): ID del modello di datalogger.
        Returns:
            dict: Dizionario contenente le capacità del modello di datalogger specificato.
        """
        dataloggers = self.get_dataloggers_series()
        for series in dataloggers:
            for model in series['models']:
                if model['id'] == model_id:
                    return model['capabilities']
        return None

    def get_datalogger_number_channels(self, model_id):
        """
        Recupera il numero di canali di un modello di datalogger specifico.
        Args:
            model_id (str): ID del modello di datalogger.
        Returns:
            int: Numero di canali del modello di datalogger specificato.
        """
        capabilities = self.get_datalogger_capabilities(model_id)
        if capabilities:
            return capabilities['channels']
        return None

    def get_datalogger_model_scpi_commands(self, model_id):
        """
        Recupera i comandi SCPI specifici per un modello di datalogger specifico.
        Args:
            model_id (str): ID del modello di datalogger.
        Returns:
            dict: Dizionario contenente i comandi SCPI specifici per il modello di datalogger specificato.
        """
        dataloggers = self.get_dataloggers_series()
        for series in dataloggers:
            for model in series['models']:
                if model['id'] == model_id:
                    return model['scpi_commands']
        return None

    def get_datalogger_supported_connection(self, model_id):
        """
        Recupera i tipi di connessione supportati per un modello di datalogger specifico.
        Args:
            model_id (str): ID del modello di datalogger.
        Returns:
            list: Lista dei tipi di connessione supportati per il modello di datalogger specificato.
        """
        dataloggers = self.get_dataloggers_series()
        for series in dataloggers:
            for model in series['models']:
                if model['id'] == model_id:
                    return model['interface']['supported_connection_types']
        return None

    def get_datalogger_supported_connection_list(self):
        """
        Recupera l'elenco dei tipi di connessione supportati per tutti i modelli di datalogger.
        Returns:
            list: Lista dei tipi di connessione supportati per tutti i modelli di datalogger.
        """
        dataloggers = self.get_dataloggers_series()
        supported_connections = []
        for series in dataloggers:
            for model in series['models']:
                supported_connections.extend(model['interface']['supported_connection_types'])
        return supported_connections

    def get_datalogger_supported_connection_type_list(self, model_id):
        """
        Recupera l'elenco dei tipi di connessione supportati per un modello di datalogger specifico.
        Args:
            model_id (str): ID del modello di datalogger.
        Returns:
            list: Lista dei tipi di connessione supportati per il modello di datalogger specificato.
        """
        dataloggers = self.get_dataloggers_series()
        for series in dataloggers:
            for model in series['models']:
                if model['id'] == model_id:
                    return [connection['type'] for connection in model['interface']['supported_connection_types']]
        return None
    
    def get_series(self, type_name):
        """
        Recupera tutte le serie disponibili per un tipo di strumento specifico.
        Args:
            type_name (str): Tipo di strumento (es. 'power_supply', 'datalogger', 'oscilloscope', 'electronic_load').
        Returns:
            list | None: Lista delle serie disponibili per il tipo di strumento specificato.
        """
        key_by_type = {
            'power_supply': 'power_supplies_series',
            'datalogger': 'dataloggers_series',
            'oscilloscope': 'oscilloscopes_series',
            'electronic_load': 'electronic_loads_series',
        }
        key = key_by_type.get(type_name)
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
                common = series.get('common_scpi_commands', {})
                for model in series.get('models', []):
                    if model.get('id') == model_id:
                        specific = model.get('scpi_commands', {})
                        return {**common, **specific}
        return None

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
        if type_name == 'power_supply':
            power_supplies = self.get_powersupplys_series()
            for series in power_supplies:
                if series['series_id'] == series_id:
                    for model in series['models']:
                        if model['id'] == model_id:
                            return model['interface']['supported_connection_types']
        elif type_name == 'datalogger':
            dataloggers = self.get_dataloggers_series()
            for series in dataloggers:
                if series['series_id'] == series_id:
                    for model in series['models']:
                        if model['id'] == model_id:
                            return model['interface']['supported_connection_types']
        else:
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
        if type_name == 'power_supply':
            power_supplies = self.get_powersupplys_series()
            for series in power_supplies:
                if series['series_id'] == series_id:
                    for model in series['models']:
                        if model['id'] == model_id:
                            return model['channels']
        elif type_name == 'datalogger':
            dataloggers = self.get_dataloggers_series()
            for series in dataloggers:
                if series['series_id'] == series_id:
                    for model in series['models']:
                        if model['id'] == model_id:
                            return model['channels']
        else:
            return None

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
            if module.get('module_id') == module_id:
                return module
        return None

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
            module_id = module.get('module_id')
            # Controlla se il modulo è nella lista dei compatibili e non è disabilitato
            if module_id in compatible_ids and not module.get('not_enabled', False):
                enabled_modules.append(module)
        
        return enabled_modules