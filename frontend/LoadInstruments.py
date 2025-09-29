import json 

class LoadInstruments:
    """
    Classe per la gestione e l'accesso agli strumenti caricati da file JSON.
    Permette di recuperare strumenti per id, nome, tipo e di accedere a parametri specifici come canali, capabilities e comandi SCPI.
    """
    def __init__(self):
        """Inizializza la lista strumenti vuota."""
        self.instruments = []

    def load_instruments(self, file_path):
        """
        Carica la lista degli strumenti da un file JSON.
        Args:
            file_path (str): Percorso del file JSON degli strumenti.
        """
        try:
            with open(file_path, 'r') as f:
                self.instruments = json.load(f)
                self.instruments = self.instruments['instrument_library']
        except FileNotFoundError:
            print(f"File not found: {file_path}")
        except json.JSONDecodeError:
            print(f"Error decoding JSON from file: {file_path}")

    def get_powersupplys_series(self):
        """
        Recupera le serie di alimentatori disponibili.
        Returns:
            list: Lista delle serie di alimentatori.
        """
        # Cerca strumenti di tipo 'power_supply' e raccoglie le loro serie
        power_supplies_series = self.instruments.get('power_supplies_series', None)

        return power_supplies_series
    
    def get_dataloggers_series(self):
        """
        Recupera le serie di datalogger disponibili.
        Returns:
            list: Lista delle serie di datalogger.
        """
        # Cerca strumenti di tipo 'datalogger' e raccoglie le loro serie
        dataloggers_series = self.instruments.get('dataloggers_series', None)

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
            type_name (str): Tipo di strumento (es. 'power_supply', 'datalogger').
        Returns:
            list: Lista delle serie disponibili per il tipo di strumento specificato.
        """
        if type_name == 'power_supply':
            return self.get_powersupplys_series()
        elif type_name == 'datalogger':
            return self.get_dataloggers_series()
        else:
            return None

    def get_models(self, type_name, series_id):
        """
        Recupera tutti i modelli per una serie e tipo specifici.
        Args:
            type_name (str): Tipo di strumento (es. 'power_supply', 'datalogger').
            series_id (str): ID della serie di strumenti.
        Returns:
            list: Lista dei modelli disponibili per la serie e il tipo specificati.
        """
        if type_name == 'power_supply':
            power_supplies = self.get_powersupplys_series()
            for series in power_supplies:
                if series['series_id'] == series_id:
                    return series['models']
        elif type_name == 'datalogger':
            dataloggers = self.get_dataloggers_series()
            for series in dataloggers:
                if series['series_id'] == series_id:
                    return series['models']
        else:
            return None

    def get_model_capabilities(self, type_name, series_id, model_id):
        """
        Recupera le capabilities di un modello specifico.
        Args:
            type_name (str): Tipo di strumento (es. 'power_supply', 'datalogger').
            series_id (str): ID della serie di strumenti.
            model_id (str): ID del modello di strumenti.
        Returns:
            dict: Dizionario contenente le capabilities del modello specificato.
        """
        if type_name == 'power_supply':
            power_supplies = self.get_powersupplys_series()
            for series in power_supplies:
                if series['series_id'] == series_id:
                    for model in series['models']:
                        if model['id'] == model_id:
                            return model['capabilities']
        elif type_name == 'datalogger':
            dataloggers = self.get_dataloggers_series()
            for series in dataloggers:
                if series['series_id'] == series_id:
                    for model in series['models']:
                        if model['id'] == model_id:
                            return model['capabilities']
        else:
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
        if type_name == 'power_supply':
            power_supplies = self.get_powersupplys_series()
            for series in power_supplies:
                if series['series_id'] == series_id:
                    for model in series['models']:
                        if model['id'] == model_id:
                            return {**model['common_scpi_commands'], **model['scpi_commands']}
        elif type_name == 'datalogger':
            dataloggers = self.get_dataloggers_series()
            for series in dataloggers:
                if series['series_id'] == series_id:
                    for model in series['models']:
                        if model['id'] == model_id:
                            return {**model['common_scpi_commands'], **model['scpi_commands']}
        else:
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
        if type_name == 'power_supply':
            power_supplies = self.get_powersupplys_series()
            for series in power_supplies:
                if series_id and series['series_id'] == series_id:
                    for model in series['models']:
                        if model_id and model['id'] == model_id:
                            return model
                elif not model_id:
                    return series
        elif type_name == 'datalogger':
            dataloggers = self.get_dataloggers_series()
            for series in dataloggers:
                if series_id and series['series_id'] == series_id:
                    for model in series['models']:
                        if model_id and model['id'] == model_id:
                            return model
                elif not model_id:
                    return series
        else:
            return None

    def get_all_types(self):
        """
        Restituisce tutti i tipi di strumenti disponibili nella libreria.
        Returns:
            list: Lista dei tipi di strumenti disponibili.
        """
        return ['power_supply', 'datalogger']

    def get_series_name(self, type_name, series_id):
        """
        Restituisce il nome leggibile di una serie dato il suo id.
        Args:
            type_name (str): Tipo di strumento (es. 'power_supply', 'datalogger').
            series_id (str): ID della serie di strumenti.
        Returns:
            str: Nome leggibile della serie.
        """
        if type_name == 'power_supply':
            power_supplies = self.get_powersupplys_series()
            for series in power_supplies:
                if series['series_id'] == series_id:
                    return series['series_name']
        elif type_name == 'datalogger':
            dataloggers = self.get_dataloggers_series()
            for series in dataloggers:
                if series['series_id'] == series_id:
                    return series['series_name']
        else:
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
        if type_name == 'power_supply':
            power_supplies = self.get_powersupplys_series()
            for series in power_supplies:
                if series['series_id'] == series_id:
                    for model in series['models']:
                        if model['id'] == model_id:
                            return model['name']
        elif type_name == 'datalogger':
            dataloggers = self.get_dataloggers_series()
            for series in dataloggers:
                if series['series_id'] == series_id:
                    for model in series['models']:
                        if model['id'] == model_id:
                            return model['name']
        else:
            return None