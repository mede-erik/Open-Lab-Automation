"""
Project Database Manager - PostgreSQL
======================================

Gestisce database PostgreSQL per progetti di automazione laboratorio.
Ogni progetto ha il proprio database.
Ogni file .eff genera tabelle con numero incrementale per ogni esecuzione.

Architettura:
- 1 Progetto = 1 Database PostgreSQL
- 1 Esecuzione efficienza = 1 Tabella (<nome_eff>_<numero>)
- Struttura tabella: variabili di misura (stringhe) + array di dati (double)

[ERROR-PJDB-XXX] per codici errore standardizzati
"""

import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values, Json
from typing import List, Dict, Any, Optional, Tuple
import json
from datetime import datetime
import re


class ProjectDatabaseManager:
    """
    Gestisce database PostgreSQL per progetti di automazione laboratorio.
    """
    
    def __init__(self, host: str = 'localhost', port: int = 5432, 
                 user: str = 'postgres', password: str = '', 
                 project_name: str = None):
        """
        Inizializza il manager del database di progetto.
        
        Args:
            host: Host PostgreSQL
            port: Porta PostgreSQL
            user: Username PostgreSQL
            password: Password PostgreSQL
            project_name: Nome del progetto (diventa nome database)
        """
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.project_name = project_name
        self.db_name = self._sanitize_db_name(project_name) if project_name else None
        self.conn = None
    
    def _sanitize_db_name(self, name: str) -> str:
        """
        Sanitizza il nome del progetto per usarlo come nome database.
        
        Args:
            name: Nome originale del progetto
            
        Returns:
            Nome database valido (lowercase, underscores, alfanumerico)
        """
        # Converte a lowercase, sostituisce spazi e caratteri speciali con underscore
        sanitized = re.sub(r'[^a-z0-9_]', '_', name.lower())
        # Rimuove underscore multipli consecutivi
        sanitized = re.sub(r'_+', '_', sanitized)
        # Rimuove underscore iniziali/finali
        sanitized = sanitized.strip('_')
        # Assicura che inizi con una lettera
        if sanitized and not sanitized[0].isalpha():
            sanitized = 'proj_' + sanitized
        return sanitized or 'unnamed_project'
    
    def _sanitize_table_name(self, eff_filename: str) -> str:
        """
        Sanitizza il nome del file .eff per usarlo come nome tabella.
        
        Args:
            eff_filename: Nome del file .eff (con o senza estensione)
            
        Returns:
            Nome tabella valido
        """
        # Rimuove estensione .eff se presente
        name = eff_filename.replace('.eff', '')
        # Sanitizza come per db_name
        sanitized = re.sub(r'[^a-z0-9_]', '_', name.lower())
        sanitized = re.sub(r'_+', '_', sanitized)
        sanitized = sanitized.strip('_')
        if sanitized and not sanitized[0].isalpha():
            sanitized = 'eff_' + sanitized
        return sanitized or 'unnamed_eff'
    
    def connect_postgres(self) -> psycopg2.extensions.connection:
        """
        Connessione al server PostgreSQL (database 'postgres' per operazioni admin).
        
        Returns:
            Connessione PostgreSQL
            
        Raises:
            Exception: [PJDB-001] Errore connessione a PostgreSQL
        """
        try:
            conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                dbname='postgres'
            )
            conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
            return conn
        except Exception as e:
            raise Exception(f"[PJDB-001] Errore connessione a PostgreSQL: {e}")
    
    def connect_project_db(self) -> psycopg2.extensions.connection:
        """
        Connessione al database del progetto.
        
        Returns:
            Connessione al database del progetto
            
        Raises:
            Exception: [PJDB-002] Database progetto non specificato o errore connessione
        """
        if not self.db_name:
            raise Exception("[PJDB-002] Nome database progetto non specificato")
        
        try:
            conn = psycopg2.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                dbname=self.db_name
            )
            return conn
        except Exception as e:
            raise Exception(f"[PJDB-002] Errore connessione al database '{self.db_name}': {e}")
    
    def create_project_database(self) -> bool:
        """
        Crea il database del progetto se non esiste.
        
        Returns:
            True se creato o già esistente, False in caso di errore
            
        Raises:
            Exception: [PJDB-003] Errore creazione database
        """
        if not self.db_name:
            raise Exception("[PJDB-003] Nome database progetto non specificato")
        
        conn = None
        try:
            conn = self.connect_postgres()
            cursor = conn.cursor()
            
            # Verifica se il database esiste
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (self.db_name,)
            )
            exists = cursor.fetchone()
            
            if not exists:
                # Crea il database
                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(
                        sql.Identifier(self.db_name)
                    )
                )
                print(f"[INFO] Database '{self.db_name}' creato con successo")
            else:
                print(f"[INFO] Database '{self.db_name}' già esistente")
            
            cursor.close()
            return True
            
        except Exception as e:
            raise Exception(f"[PJDB-003] Errore creazione database '{self.db_name}': {e}")
        finally:
            if conn:
                conn.close()
    
    def get_next_table_number(self, eff_base_name: str) -> int:
        """
        Ottiene il prossimo numero incrementale per una tabella di efficienza.
        
        Args:
            eff_base_name: Nome base del file .eff
            
        Returns:
            Prossimo numero incrementale (es. se esistono eff_1, eff_2 ritorna 3)
            
        Raises:
            Exception: [PJDB-004] Errore ricerca tabelle
        """
        sanitized_name = self._sanitize_table_name(eff_base_name)
        
        try:
            conn = self.connect_project_db()
            cursor = conn.cursor()
            
            # Cerca tutte le tabelle che iniziano con il nome base
            cursor.execute("""
                SELECT tablename 
                FROM pg_tables 
                WHERE schemaname = 'public' 
                AND tablename LIKE %s
            """, (f"{sanitized_name}_%",))
            
            tables = cursor.fetchall()
            cursor.close()
            conn.close()
            
            if not tables:
                return 1
            
            # Estrae i numeri dalle tabelle esistenti
            numbers = []
            pattern = re.compile(rf"{re.escape(sanitized_name)}_(\d+)$")
            for (table_name,) in tables:
                match = pattern.match(table_name)
                if match:
                    numbers.append(int(match.group(1)))
            
            return max(numbers) + 1 if numbers else 1
            
        except Exception as e:
            raise Exception(f"[PJDB-004] Errore ricerca tabelle per '{eff_base_name}': {e}")
    
    def create_efficiency_table(
        self, 
        eff_filename: str,
        measurement_vars: Dict[str, str],
        sweep_variables: List[str],
        data_columns: List[str]
    ) -> str:
        """
        Crea una nuova tabella per un'esecuzione di efficienza.
        
        Args:
            eff_filename: Nome del file .eff
            measurement_vars: Dizionario delle variabili di misura (nome: tipo_sql)
                             es. {'operator': 'VARCHAR(100)', 'notes': 'TEXT', 'timestamp': 'TIMESTAMP'}
            sweep_variables: Lista delle variabili di sweep (es. ['vin', 'iout'])
            data_columns: Lista delle colonne dati (es. ['efficiency', 'power_loss', 'temperature'])
            
        Returns:
            Nome completo della tabella creata (es. 'eff_1')
            
        Raises:
            Exception: [PJDB-005] Errore creazione tabella
        """
        base_name = self._sanitize_table_name(eff_filename)
        table_number = self.get_next_table_number(base_name)
        table_name = f"{base_name}_{table_number}"
        
        try:
            conn = self.connect_project_db()
            cursor = conn.cursor()
            
            # Costruisce le colonne della tabella
            columns = []
            
            # ID auto-incrementale
            columns.append("id SERIAL PRIMARY KEY")
            
            # Variabili di misura (stringhe/timestamp)
            for var_name, var_type in measurement_vars.items():
                columns.append(f"{var_name} {var_type}")
            
            # Variabili di sweep (DOUBLE PRECISION)
            for sweep_var in sweep_variables:
                columns.append(f"{sweep_var} DOUBLE PRECISION")
            
            # Colonne dati (DOUBLE PRECISION)
            for data_col in data_columns:
                columns.append(f"{data_col} DOUBLE PRECISION")
            
            # Timestamp di creazione record
            columns.append("created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            
            # Crea la tabella
            create_query = sql.SQL("CREATE TABLE {} ({})").format(
                sql.Identifier(table_name),
                sql.SQL(", ".join(columns))
            )
            
            cursor.execute(create_query)
            
            # Crea indici per migliorare le query
            for sweep_var in sweep_variables:
                index_name = f"idx_{table_name}_{sweep_var}"
                cursor.execute(
                    sql.SQL("CREATE INDEX {} ON {} ({})").format(
                        sql.Identifier(index_name),
                        sql.Identifier(table_name),
                        sql.Identifier(sweep_var)
                    )
                )
            
            conn.commit()
            cursor.close()
            conn.close()
            
            print(f"[INFO] Tabella '{table_name}' creata con successo")
            return table_name
            
        except Exception as e:
            if conn:
                conn.rollback()
                conn.close()
            raise Exception(f"[PJDB-005] Errore creazione tabella '{table_name}': {e}")
    
    def insert_measurement_data(
        self,
        table_name: str,
        measurement_info: Dict[str, Any],
        data_rows: List[Dict[str, Any]]
    ) -> int:
        """
        Inserisce dati di misura nella tabella.
        
        Args:
            table_name: Nome della tabella
            measurement_info: Dizionario con le variabili di misura comuni
                             es. {'operator': 'Mario', 'notes': 'Test 1', 'timestamp': datetime.now()}
            data_rows: Lista di dizionari con i dati punto per punto
                      es. [{'vin': 12.0, 'iout': 1.0, 'efficiency': 95.2, ...}, ...]
        
        Returns:
            Numero di righe inserite
            
        Raises:
            Exception: [PJDB-006] Errore inserimento dati
        """
        try:
            conn = self.connect_project_db()
            cursor = conn.cursor()
            
            # Prepara i dati da inserire
            insert_data = []
            for row in data_rows:
                # Combina measurement_info con i dati del punto
                full_row = {**measurement_info, **row}
                insert_data.append(full_row)
            
            if not insert_data:
                return 0
            
            # Estrae le colonne (escluso 'id' e 'created_at' che sono auto-generati)
            columns = list(insert_data[0].keys())
            
            # Prepara la query di inserimento
            insert_query = sql.SQL("INSERT INTO {} ({}) VALUES %s").format(
                sql.Identifier(table_name),
                sql.SQL(", ").join(map(sql.Identifier, columns))
            )
            
            # Prepara i valori
            values = [[row[col] for col in columns] for row in insert_data]
            
            # Esegue l'inserimento batch
            execute_values(cursor, insert_query.as_string(conn), values)
            
            rows_inserted = cursor.rowcount
            conn.commit()
            cursor.close()
            conn.close()
            
            print(f"[INFO] {rows_inserted} righe inserite in '{table_name}'")
            return rows_inserted
            
        except Exception as e:
            if conn:
                conn.rollback()
                conn.close()
            raise Exception(f"[PJDB-006] Errore inserimento dati in '{table_name}': {e}")
    
    def list_project_tables(self) -> List[str]:
        """
        Lista tutte le tabelle nel database del progetto.
        
        Returns:
            Lista dei nomi delle tabelle
            
        Raises:
            Exception: [PJDB-007] Errore lettura tabelle
        """
        try:
            conn = self.connect_project_db()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT tablename 
                FROM pg_tables 
                WHERE schemaname = 'public'
                ORDER BY tablename
            """)
            
            tables = [row[0] for row in cursor.fetchall()]
            
            cursor.close()
            conn.close()
            
            return tables
            
        except Exception as e:
            raise Exception(f"[PJDB-007] Errore lettura tabelle: {e}")
    
    def get_table_data(
        self,
        table_name: str,
        conditions: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Recupera dati da una tabella con filtri opzionali.
        
        Args:
            table_name: Nome della tabella
            conditions: Dizionario di condizioni WHERE (es. {'vin': 12.0})
            limit: Numero massimo di righe da restituire
            
        Returns:
            Lista di dizionari con i dati
            
        Raises:
            Exception: [PJDB-008] Errore lettura dati
        """
        try:
            conn = self.connect_project_db()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            
            # Costruisce la query
            query = sql.SQL("SELECT * FROM {}").format(sql.Identifier(table_name))
            params = []
            
            if conditions:
                where_clauses = []
                for col, val in conditions.items():
                    where_clauses.append(sql.SQL("{} = %s").format(sql.Identifier(col)))
                    params.append(val)
                
                query = sql.SQL("{} WHERE {}").format(
                    query,
                    sql.SQL(" AND ").join(where_clauses)
                )
            
            if limit:
                query = sql.SQL("{} LIMIT %s").format(query)
                params.append(limit)
            
            cursor.execute(query, params)
            results = cursor.fetchall()
            
            cursor.close()
            conn.close()
            
            return [dict(row) for row in results]
            
        except Exception as e:
            raise Exception(f"[PJDB-008] Errore lettura dati da '{table_name}': {e}")
    
    def delete_project_database(self) -> bool:
        """
        ATTENZIONE: Elimina completamente il database del progetto.
        
        Returns:
            True se eliminato con successo
            
        Raises:
            Exception: [PJDB-009] Errore eliminazione database
        """
        if not self.db_name:
            raise Exception("[PJDB-009] Nome database progetto non specificato")
        
        conn = None
        try:
            conn = self.connect_postgres()
            cursor = conn.cursor()
            
            # Termina le connessioni attive al database
            cursor.execute("""
                SELECT pg_terminate_backend(pg_stat_activity.pid)
                FROM pg_stat_activity
                WHERE pg_stat_activity.datname = %s
                AND pid <> pg_backend_pid()
            """, (self.db_name,))
            
            # Elimina il database
            cursor.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(
                    sql.Identifier(self.db_name)
                )
            )
            
            cursor.close()
            print(f"[WARNING] Database '{self.db_name}' eliminato")
            return True
            
        except Exception as e:
            raise Exception(f"[PJDB-009] Errore eliminazione database '{self.db_name}': {e}")
        finally:
            if conn:
                conn.close()


# Esempio di utilizzo
if __name__ == "__main__":
    # Configurazione
    db_config = {
        'host': 'localhost',
        'port': 5432,
        'user': 'postgres',
        'password': 'your_password'
    }
    
    # Crea manager per il progetto
    manager = ProjectDatabaseManager(
        **db_config,
        project_name="Test DC-DC Converter"
    )
    
    print(f"Nome database sanitizzato: {manager.db_name}")
    
    # Crea il database del progetto
    manager.create_project_database()
    
    # Definisce la struttura di una tabella di efficienza
    measurement_vars = {
        'operator': 'VARCHAR(100)',
        'notes': 'TEXT',
        'test_date': 'TIMESTAMP',
        'ambient_temp': 'DOUBLE PRECISION'
    }
    
    sweep_vars = ['vin', 'iout']
    data_cols = ['efficiency', 'power_loss', 'temperature']
    
    # Crea la tabella
    table_name = manager.create_efficiency_table(
        'Eff.eff',
        measurement_vars,
        sweep_vars,
        data_cols
    )
    
    # Inserisce dati di esempio
    measurement_info = {
        'operator': 'Mario Rossi',
        'notes': 'Test di efficienza con carico variabile',
        'test_date': datetime.now(),
        'ambient_temp': 25.0
    }
    
    data_rows = [
        {'vin': 12.0, 'iout': 1.0, 'efficiency': 95.2, 'power_loss': 0.5, 'temperature': 45.0},
        {'vin': 12.0, 'iout': 2.0, 'efficiency': 94.8, 'power_loss': 1.2, 'temperature': 48.0},
        {'vin': 15.0, 'iout': 1.0, 'efficiency': 96.1, 'power_loss': 0.4, 'temperature': 43.0},
        {'vin': 15.0, 'iout': 2.0, 'efficiency': 95.5, 'power_loss': 1.0, 'temperature': 46.0},
    ]
    
    manager.insert_measurement_data(table_name, measurement_info, data_rows)
    
    # Lista tabelle
    tables = manager.list_project_tables()
    print(f"\nTabelle nel progetto: {tables}")
    
    # Legge dati
    data = manager.get_table_data(table_name, limit=2)
    print(f"\nPrime 2 righe di '{table_name}':")
    for row in data:
        print(row)
