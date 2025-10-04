import psycopg2
from psycopg2.extras import execute_values
from typing import List, Dict, Any, Optional
import numpy as np
from datetime import datetime

class DatabaseManager:
    """Gestisce la connessione e le operazioni sul database PostgreSQL/TimescaleDB."""
    
    def __init__(self, host: str, port: int, dbname: str, user: str, password: str):
        """Inizializza il gestore database con i parametri di connessione."""
        self.conn_params = {
            'host': host,
            'port': port,
            'dbname': dbname,
            'user': user,
            'password': password
        }
        self.conn = None
        self.connect()

    def connect(self) -> None:
        """Stabilisce la connessione al database."""
        try:
            self.conn = psycopg2.connect(**self.conn_params)
        except Exception as e:
            raise Exception(f"Errore di connessione al database: {str(e)}")

    def ensure_connection(self) -> None:
        """Verifica e ripristina la connessione se necessario."""
        if self.conn is None or self.conn.closed:
            self.connect()

    def create_project(self, name: str, description: str = "") -> int:
        """
        Crea un nuovo progetto nel database.
        
        Args:
            name: Nome del progetto
            description: Descrizione opzionale
            
        Returns:
            ID del progetto creato
        """
        self.ensure_connection()
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO progetti (nome, descrizione) VALUES (%s, %s) RETURNING id_progetto",
                (name, description)
            )
            project_id = cur.fetchone()[0]
            self.conn.commit()
            return project_id

    def create_sweep_session(
        self, 
        project_id: int, 
        name: str, 
        vin_points: List[float], 
        iout_points: List[float],
        notes: str = ""
    ) -> int:
        """
        Crea una nuova sessione di sweep nel database.
        
        Args:
            project_id: ID del progetto
            name: Nome della sessione
            vin_points: Lista dei punti di tensione di ingresso
            iout_points: Lista dei punti di corrente di uscita
            notes: Note opzionali
            
        Returns:
            ID della sessione creata
        """
        self.ensure_connection()
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO sessioni_sweep 
                (id_progetto, nome, vin_array, iout_array, note)
                VALUES (%s, %s, %s::numeric[], %s::numeric[], %s)
                RETURNING id_sessione
                """,
                (project_id, name, vin_points, iout_points, notes)
            )
            session_id = cur.fetchone()[0]
            self.conn.commit()
            return session_id

    def add_measurement_point(
        self,
        session_id: int,
        vin_target: float,
        iout_target: float,
        vin_real: float,
        iin_real: float,
        vout_real: float,
        iout_real: float,
        temperature: float,
        notes: str = ""
    ) -> int:
        """
        Aggiunge un nuovo punto di misura.
        
        Calcola automaticamente efficienza, Pin e Pout.
        
        Args:
            session_id: ID della sessione
            vin_target: Tensione di ingresso target
            iout_target: Corrente di uscita target
            vin_real: Tensione di ingresso misurata
            iin_real: Corrente di ingresso misurata
            vout_real: Tensione di uscita misurata
            iout_real: Corrente di uscita misurata
            temperature: Temperatura misurata
            notes: Note opzionali
            
        Returns:
            ID del punto di misura creato
        """
        # Calcola potenze ed efficienza
        pin = vin_real * iin_real
        pout = vout_real * iout_real
        efficiency = (pout / pin * 100) if pin > 0 else 0

        self.ensure_connection()
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO punti_misura (
                    id_sessione, vin_target, iout_target,
                    vin_reale, iin_reale, vout_reale, iout_reale,
                    temperatura, efficienza, pin, pout, note
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id_punto
                """,
                (
                    session_id, vin_target, iout_target,
                    vin_real, iin_real, vout_real, iout_real,
                    temperature, efficiency, pin, pout, notes
                )
            )
            point_id = cur.fetchone()[0]
            self.conn.commit()
            return point_id

    def add_waveform_data(
        self,
        point_id: int,
        channel: int,
        timestamps: List[datetime],
        values: List[float]
    ) -> None:
        """
        Aggiunge i dati di una forma d'onda per un punto di misura.
        
        Usa psycopg2.extras.execute_values per inserimento bulk efficiente.
        
        Args:
            point_id: ID del punto di misura
            channel: Numero del canale dell'oscilloscopio
            timestamps: Lista dei timestamp dei campioni
            values: Lista dei valori dei campioni
        """
        if len(timestamps) != len(values):
            raise ValueError("Le liste timestamps e values devono avere la stessa lunghezza")

        self.ensure_connection()
        with self.conn.cursor() as cur:
            # Prepara i dati per l'inserimento bulk
            data = [
                (point_id, ts, channel, val)
                for ts, val in zip(timestamps, values)
            ]
            
            # Usa execute_values per inserimento bulk efficiente
            execute_values(
                cur,
                """
                INSERT INTO forme_d_onda 
                (id_punto, timestamp, canale, valore)
                VALUES %s
                """,
                data,
                template="(%s, %s, %s, %s)",
                page_size=1000  # Ottimizza per grandi dataset
            )
            self.conn.commit()

    def get_efficiency_map(self, session_id: int) -> Dict[str, List[Any]]:
        """
        Recupera la mappa di efficienza per una sessione.
        
        Args:
            session_id: ID della sessione
            
        Returns:
            Dizionario con liste di valori per ogni parametro
        """
        self.ensure_connection()
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT 
                    vin_target, iout_target,
                    efficienza, temperatura
                FROM punti_misura
                WHERE id_sessione = %s
                ORDER BY vin_target, iout_target
                """,
                (session_id,)
            )
            rows = cur.fetchall()
            
            # Organizza i dati in un dizionario di liste
            result = {
                'vin': [row[0] for row in rows],
                'iout': [row[1] for row in rows],
                'efficiency': [row[2] for row in rows],
                'temperature': [row[3] for row in rows]
            }
            return result

    def get_waveform_data(
        self,
        point_id: int,
        channel: int,
        start_time: datetime,
        end_time: datetime,
        downsample_us: Optional[int] = None
    ) -> Dict[str, List[Any]]:
        """
        Recupera i dati di una forma d'onda, opzionalmente con downsampling.
        
        Args:
            point_id: ID del punto di misura
            channel: Numero del canale
            start_time: Timestamp di inizio
            end_time: Timestamp di fine
            downsample_us: Se specificato, applica il downsampling con bucket 
                         della dimensione specificata in microsecondi
                         
        Returns:
            Dizionario con timestamps e valori
        """
        self.ensure_connection()
        with self.conn.cursor() as cur:
            if downsample_us is None:
                # Recupera tutti i punti
                cur.execute(
                    """
                    SELECT timestamp, valore
                    FROM forme_d_onda
                    WHERE 
                        id_punto = %s AND
                        canale = %s AND
                        timestamp BETWEEN %s AND %s
                    ORDER BY timestamp
                    """,
                    (point_id, channel, start_time, end_time)
                )
                rows = cur.fetchall()
                return {
                    'timestamps': [row[0] for row in rows],
                    'values': [row[1] for row in rows]
                }
            else:
                # Applica il downsampling
                cur.execute(
                    """
                    SELECT 
                        time_bucket(%s, timestamp) AS bucket,
                        avg(valore) as value_avg,
                        min(valore) as value_min,
                        max(valore) as value_max
                    FROM forme_d_onda
                    WHERE 
                        id_punto = %s AND
                        canale = %s AND
                        timestamp BETWEEN %s AND %s
                    GROUP BY bucket
                    ORDER BY bucket
                    """,
                    (
                        f"{downsample_us} microseconds",
                        point_id, channel,
                        start_time, end_time
                    )
                )
                rows = cur.fetchall()
                return {
                    'timestamps': [row[0] for row in rows],
                    'values_avg': [row[1] for row in rows],
                    'values_min': [row[2] for row in rows],
                    'values_max': [row[3] for row in rows]
                }

    def close(self) -> None:
        """Chiude la connessione al database."""
        if self.conn:
            self.conn.close()
            self.conn = None
