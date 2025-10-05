"""
Data models for DC-DC converter measurement system.

This module provides object-oriented interfaces for database operations,
implementing CRUD operations for Projects, SweepSessions, MeasurementPoints,
and Waveforms.
"""

from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from decimal import Decimal
import json
from .database import DatabaseManager
from .logger import Logger


class Project:
    """
    Project model for managing DC-DC converter measurement projects.
    Represents a collection of measurement sessions with global parameters.
    """
    
    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize Project model with database manager.
        
        Args:
            db_manager: DatabaseManager instance for database operations
        """
        self.db = db_manager
        self.logger = Logger()
        self.id_progetto: Optional[int] = None
        self.nome_progetto: Optional[str] = None
        self.descrizione: Optional[str] = None
        self.data_creazione: Optional[datetime] = None
        self.data_modifica: Optional[datetime] = None
        self.parametri_globali: Optional[Dict[str, Any]] = None
    
    def create(self, nome_progetto: str, descrizione: str = None, 
               parametri_globali: Dict[str, Any] = None) -> bool:
        """
        Create a new project in the database.
        
        Args:
            nome_progetto: Unique project name
            descrizione: Optional project description
            parametri_globali: Optional global project parameters
            
        Returns:
            bool: True if creation successful
        """
        try:
            query = """
                INSERT INTO progetti (nome_progetto, descrizione, parametri_globali)
                VALUES (%s, %s, %s)
                RETURNING id_progetto, data_creazione, data_modifica;
            """
            params = (nome_progetto, descrizione, 
                     json.dumps(parametri_globali) if parametri_globali else None)
            
            results = self.db.execute_query(query, params, fetch_results=True)
            if results:
                result = results[0]
                self.id_progetto = result['id_progetto']
                self.nome_progetto = nome_progetto
                self.descrizione = descrizione
                self.data_creazione = result['data_creazione']
                self.data_modifica = result['data_modifica']
                self.parametri_globali = parametri_globali
                
                self.logger.info(f"Created project: {nome_progetto} (ID: {self.id_progetto})")
                return True
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to create project: {str(e)}")
            return False
    
    def load_by_id(self, project_id: int) -> bool:
        """
        Load project data by ID from database.
        
        Args:
            project_id: Project ID to load
            
        Returns:
            bool: True if loading successful
        """
        try:
            query = """
                SELECT id_progetto, nome_progetto, descrizione, 
                       data_creazione, data_modifica, parametri_globali
                FROM progetti WHERE id_progetto = %s;
            """
            results = self.db.execute_query(query, (project_id,), fetch_results=True)
            
            if results:
                row = results[0]
                self.id_progetto = row['id_progetto']
                self.nome_progetto = row['nome_progetto']
                self.descrizione = row['descrizione']
                self.data_creazione = row['data_creazione']
                self.data_modifica = row['data_modifica']
                self.parametri_globali = json.loads(row['parametri_globali']) if row['parametri_globali'] else None
                
                self.logger.debug(f"Loaded project: {self.nome_progetto} (ID: {self.id_progetto})")
                return True
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to load project {project_id}: {str(e)}")
            return False
    
    def load_by_name(self, project_name: str) -> bool:
        """
        Load project data by name from database.
        
        Args:
            project_name: Project name to load
            
        Returns:
            bool: True if loading successful
        """
        try:
            query = """
                SELECT id_progetto, nome_progetto, descrizione, 
                       data_creazione, data_modifica, parametri_globali
                FROM progetti WHERE nome_progetto = %s;
            """
            results = self.db.execute_query(query, (project_name,), fetch_results=True)
            
            if results:
                row = results[0]
                self.id_progetto = row['id_progetto']
                self.nome_progetto = row['nome_progetto']
                self.descrizione = row['descrizione']
                self.data_creazione = row['data_creazione']
                self.data_modifica = row['data_modifica']
                self.parametri_globali = json.loads(row['parametri_globali']) if row['parametri_globali'] else None
                
                self.logger.debug(f"Loaded project by name: {self.nome_progetto} (ID: {self.id_progetto})")
                return True
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to load project '{project_name}': {str(e)}")
            return False
    
    def update(self) -> bool:
        """
        Update project data in database.
        
        Returns:
            bool: True if update successful
        """
        if not self.id_progetto:
            self.logger.error("Cannot update project: no ID set")
            return False
        
        try:
            query = """
                UPDATE progetti 
                SET nome_progetto = %s, descrizione = %s, parametri_globali = %s,
                    data_modifica = NOW()
                WHERE id_progetto = %s
                RETURNING data_modifica;
            """
            params = (self.nome_progetto, self.descrizione,
                     json.dumps(self.parametri_globali) if self.parametri_globali else None,
                     self.id_progetto)
            
            results = self.db.execute_query(query, params, fetch_results=True)
            if results:
                self.data_modifica = results[0]['data_modifica']
                self.logger.info(f"Updated project: {self.nome_progetto} (ID: {self.id_progetto})")
                return True
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to update project: {str(e)}")
            return False
    
    def delete(self) -> bool:
        """
        Delete project from database (cascades to sessions and measurements).
        
        Returns:
            bool: True if deletion successful
        """
        if not self.id_progetto:
            self.logger.error("Cannot delete project: no ID set")
            return False
        
        try:
            query = "DELETE FROM progetti WHERE id_progetto = %s;"
            self.db.execute_query(query, (self.id_progetto,), fetch_results=False)
            
            self.logger.info(f"Deleted project: {self.nome_progetto} (ID: {self.id_progetto})")
            # Clear instance data
            self.id_progetto = None
            self.nome_progetto = None
            self.descrizione = None
            self.data_creazione = None
            self.data_modifica = None
            self.parametri_globali = None
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to delete project: {str(e)}")
            return False
    
    @staticmethod
    def list_all(db_manager: DatabaseManager) -> List[Dict[str, Any]]:
        """
        Get list of all projects in database.
        
        Args:
            db_manager: DatabaseManager instance
            
        Returns:
            List of project dictionaries
        """
        try:
            query = """
                SELECT id_progetto, nome_progetto, descrizione, 
                       data_creazione, data_modifica
                FROM progetti 
                ORDER BY data_creazione DESC;
            """
            results = db_manager.execute_query(query, fetch_results=True)
            return results if results else []
            
        except Exception as e:
            Logger().error(f"Failed to list projects: {str(e)}")
            return []


class SweepSession:
    """
    SweepSession model for managing measurement sweep sessions.
    Represents a series of measurement points with defined input parameters.
    """
    
    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize SweepSession model with database manager.
        
        Args:
            db_manager: DatabaseManager instance for database operations
        """
        self.db = db_manager
        self.logger = Logger()
        self.id_sessione: Optional[int] = None
        self.id_progetto: Optional[int] = None
        self.nome_sessione: Optional[str] = None
        self.data_inizio: Optional[datetime] = None
        self.data_fine: Optional[datetime] = None
        self.valori_vin: Optional[List[Decimal]] = None
        self.valori_iout: Optional[List[Decimal]] = None
        self.stato_sessione: str = 'in_corso'
        self.note: Optional[str] = None
    
    def create(self, id_progetto: int, nome_sessione: str, 
               valori_vin: List[float], valori_iout: List[float],
               note: str = None) -> bool:
        """
        Create a new sweep session in the database.
        
        Args:
            id_progetto: Parent project ID
            nome_sessione: Session name
            valori_vin: List of input voltage values for sweep
            valori_iout: List of output current values for sweep
            note: Optional session notes
            
        Returns:
            bool: True if creation successful
        """
        try:
            query = """
                INSERT INTO sessioni_sweep (id_progetto, nome_sessione, valori_vin, valori_iout, note)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id_sessione, data_inizio;
            """
            params = (id_progetto, nome_sessione, valori_vin, valori_iout, note)
            
            results = self.db.execute_query(query, params, fetch_results=True)
            if results:
                result = results[0]
                self.id_sessione = result['id_sessione']
                self.id_progetto = id_progetto
                self.nome_sessione = nome_sessione
                self.data_inizio = result['data_inizio']
                self.valori_vin = [Decimal(str(v)) for v in valori_vin]
                self.valori_iout = [Decimal(str(v)) for v in valori_iout]
                self.note = note
                
                self.logger.info(f"Created sweep session: {nome_sessione} (ID: {self.id_sessione})")
                return True
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to create sweep session: {str(e)}")
            return False
    
    def load_by_id(self, session_id: int) -> bool:
        """
        Load sweep session data by ID from database.
        
        Args:
            session_id: Session ID to load
            
        Returns:
            bool: True if loading successful
        """
        try:
            query = """
                SELECT id_sessione, id_progetto, nome_sessione, data_inizio, data_fine,
                       valori_vin, valori_iout, stato_sessione, note
                FROM sessioni_sweep WHERE id_sessione = %s;
            """
            results = self.db.execute_query(query, (session_id,), fetch_results=True)
            
            if results:
                row = results[0]
                self.id_sessione = row['id_sessione']
                self.id_progetto = row['id_progetto']
                self.nome_sessione = row['nome_sessione']
                self.data_inizio = row['data_inizio']
                self.data_fine = row['data_fine']
                self.valori_vin = row['valori_vin']
                self.valori_iout = row['valori_iout']
                self.stato_sessione = row['stato_sessione']
                self.note = row['note']
                
                self.logger.debug(f"Loaded sweep session: {self.nome_sessione} (ID: {self.id_sessione})")
                return True
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to load sweep session {session_id}: {str(e)}")
            return False
    
    def complete_session(self) -> bool:
        """
        Mark session as completed and set end time.
        
        Returns:
            bool: True if update successful
        """
        if not self.id_sessione:
            self.logger.error("Cannot complete session: no ID set")
            return False
        
        try:
            query = """
                UPDATE sessioni_sweep 
                SET stato_sessione = 'completata', data_fine = NOW()
                WHERE id_sessione = %s
                RETURNING data_fine;
            """
            results = self.db.execute_query(query, (self.id_sessione,), fetch_results=True)
            
            if results:
                self.data_fine = results[0]['data_fine']
                self.stato_sessione = 'completata'
                self.logger.info(f"Completed sweep session: {self.nome_sessione} (ID: {self.id_sessione})")
                return True
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to complete session: {str(e)}")
            return False
    
    def get_measurement_points(self) -> List[Dict[str, Any]]:
        """
        Get all measurement points for this session.
        
        Returns:
            List of measurement point dictionaries
        """
        if not self.id_sessione:
            return []
        
        try:
            query = """
                SELECT id_punto, vin_target, iout_target, timestamp_misura,
                       vin_reale, vout_reale, iout_reale, iin_reale,
                       efficienza, temperatura, potenza_in, potenza_out,
                       ha_forma_onda, note_punto
                FROM punti_misura 
                WHERE id_sessione = %s
                ORDER BY timestamp_misura;
            """
            results = self.db.execute_query(query, (self.id_sessione,), fetch_results=True)
            return results if results else []
            
        except Exception as e:
            self.logger.error(f"Failed to get measurement points: {str(e)}")
            return []


class MeasurementPoint:
    """
    MeasurementPoint model for individual measurement data points.
    Represents scalar measurements at specific input conditions.
    """
    
    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize MeasurementPoint model with database manager.
        
        Args:
            db_manager: DatabaseManager instance for database operations
        """
        self.db = db_manager
        self.logger = Logger()
        self.id_punto: Optional[int] = None
        self.id_sessione: Optional[int] = None
        self.vin_target: Optional[Decimal] = None
        self.iout_target: Optional[Decimal] = None
        self.timestamp_misura: Optional[datetime] = None
        # Measured values
        self.vin_reale: Optional[Decimal] = None
        self.vout_reale: Optional[Decimal] = None
        self.iout_reale: Optional[Decimal] = None
        self.iin_reale: Optional[Decimal] = None
        self.efficienza: Optional[Decimal] = None
        self.temperatura: Optional[Decimal] = None
        self.potenza_in: Optional[Decimal] = None
        self.potenza_out: Optional[Decimal] = None
        self.ha_forma_onda: bool = False
        self.note_punto: Optional[str] = None
    
    def create(self, id_sessione: int, vin_target: float, iout_target: float,
               measurements: Dict[str, float] = None, note_punto: str = None) -> bool:
        """
        Create a new measurement point in the database.
        
        Args:
            id_sessione: Parent session ID
            vin_target: Target input voltage
            iout_target: Target output current
            measurements: Dictionary of measured values
            note_punto: Optional measurement notes
            
        Returns:
            bool: True if creation successful
        """
        try:
            # Extract measurements with defaults
            meas = measurements or {}
            
            query = """
                INSERT INTO punti_misura (
                    id_sessione, vin_target, iout_target,
                    vin_reale, vout_reale, iout_reale, iin_reale,
                    efficienza, temperatura, potenza_in, potenza_out,
                    ha_forma_onda, note_punto
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id_punto, timestamp_misura;
            """
            params = (
                id_sessione, vin_target, iout_target,
                meas.get('vin_reale'), meas.get('vout_reale'),
                meas.get('iout_reale'), meas.get('iin_reale'),
                meas.get('efficienza'), meas.get('temperatura'),
                meas.get('potenza_in'), meas.get('potenza_out'),
                meas.get('ha_forma_onda', False), note_punto
            )
            
            results = self.db.execute_query(query, params, fetch_results=True)
            if results:
                result = results[0]
                self.id_punto = result['id_punto']
                self.id_sessione = id_sessione
                self.vin_target = Decimal(str(vin_target))
                self.iout_target = Decimal(str(iout_target))
                self.timestamp_misura = result['timestamp_misura']
                
                # Set measured values
                for key, value in meas.items():
                    if hasattr(self, key) and value is not None:
                        setattr(self, key, Decimal(str(value)) if isinstance(value, (int, float)) else value)
                
                self.note_punto = note_punto
                
                self.logger.debug(f"Created measurement point: Vin={vin_target}V, Iout={iout_target}A (ID: {self.id_punto})")
                return True
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to create measurement point: {str(e)}")
            return False
    
    def load_by_id(self, point_id: int) -> bool:
        """
        Load measurement point data by ID from database.
        
        Args:
            point_id: Measurement point ID to load
            
        Returns:
            bool: True if loading successful
        """
        try:
            query = """
                SELECT id_punto, id_sessione, vin_target, iout_target, timestamp_misura,
                       vin_reale, vout_reale, iout_reale, iin_reale,
                       efficienza, temperatura, potenza_in, potenza_out,
                       ha_forma_onda, note_punto
                FROM punti_misura WHERE id_punto = %s;
            """
            results = self.db.execute_query(query, (point_id,), fetch_results=True)
            
            if results:
                row = results[0]
                for key, value in row.items():
                    if hasattr(self, key):
                        setattr(self, key, value)
                
                self.logger.debug(f"Loaded measurement point: ID {self.id_punto}")
                return True
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to load measurement point {point_id}: {str(e)}")
            return False


class Waveform:
    """
    Waveform model for managing oscilloscope waveform data.
    Handles bulk operations for time-series waveform samples.
    """
    
    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize Waveform model with database manager.
        
        Args:
            db_manager: DatabaseManager instance for database operations
        """
        self.db = db_manager
        self.logger = Logger()
    
    def save_waveform_bulk(self, id_punto: int, canale: int, tipo_misura: str,
                          timestamps: List[datetime], values: List[float],
                          frequenza_campionamento: float = None,
                          risoluzione_verticale: float = None) -> bool:
        """
        Save waveform data using bulk insert for optimal performance.
        
        Args:
            id_punto: Measurement point ID
            canale: Oscilloscope channel number
            tipo_misura: Type of measurement ('tensione', 'corrente', 'potenza')
            timestamps: List of sample timestamps
            values: List of sample values
            frequenza_campionamento: Sampling frequency in Hz
            risoluzione_verticale: Vertical resolution of ADC
            
        Returns:
            bool: True if save successful
        """
        if len(timestamps) != len(values):
            self.logger.error("Timestamps and values arrays must have same length")
            return False
        
        try:
            # Prepare bulk insert data
            insert_data = []
            for i, (timestamp, value) in enumerate(zip(timestamps, values)):
                insert_data.append((
                    timestamp, id_punto, canale, tipo_misura, value, i,
                    frequenza_campionamento, risoluzione_verticale
                ))
            
            query = """
                INSERT INTO forme_d_onda (
                    timestamp_campione, id_punto, canale, tipo_misura, valore,
                    indice_campione, frequenza_campionamento, risoluzione_verticale
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """
            
            success = self.db.execute_many(query, insert_data)
            if success:
                self.logger.info(f"Saved {len(insert_data)} waveform samples for point {id_punto}, channel {canale}")
                
                # Mark measurement point as having waveform data
                self._mark_point_has_waveform(id_punto)
                
            return success
            
        except Exception as e:
            self.logger.error(f"Failed to save waveform data: {str(e)}")
            return False
    
    def _mark_point_has_waveform(self, id_punto: int):
        """
        Mark measurement point as having waveform data.
        
        Args:
            id_punto: Measurement point ID
        """
        try:
            query = "UPDATE punti_misura SET ha_forma_onda = TRUE WHERE id_punto = %s;"
            self.db.execute_query(query, (id_punto,), fetch_results=False)
        except Exception as e:
            self.logger.warning(f"Failed to mark point as having waveform: {str(e)}")
    
    def get_waveform_data(self, id_punto: int, canale: int = None, 
                         tipo_misura: str = None, limit: int = None) -> List[Dict[str, Any]]:
        """
        Retrieve waveform data for a measurement point.
        
        Args:
            id_punto: Measurement point ID
            canale: Optional channel filter
            tipo_misura: Optional measurement type filter
            limit: Optional limit on number of samples
            
        Returns:
            List of waveform sample dictionaries
        """
        try:
            conditions = ["id_punto = %s"]
            params = [id_punto]
            
            if canale is not None:
                conditions.append("canale = %s")
                params.append(canale)
            
            if tipo_misura is not None:
                conditions.append("tipo_misura = %s")
                params.append(tipo_misura)
            
            where_clause = " AND ".join(conditions)
            limit_clause = f" LIMIT {limit}" if limit else ""
            
            query = f"""
                SELECT timestamp_campione, canale, tipo_misura, valore, indice_campione,
                       frequenza_campionamento, risoluzione_verticale
                FROM forme_d_onda 
                WHERE {where_clause}
                ORDER BY indice_campione{limit_clause};
            """
            
            results = self.db.execute_query(query, tuple(params), fetch_results=True)
            return results if results else []
            
        except Exception as e:
            self.logger.error(f"Failed to get waveform data: {str(e)}")
            return []
    
    def get_waveform_downsampled(self, id_punto: int, canale: int, tipo_misura: str,
                                bucket_interval: str = '100 microseconds') -> List[Dict[str, Any]]:
        """
        Get downsampled waveform data using PostgreSQL date_bin function.
        
        Args:
            id_punto: Measurement point ID
            canale: Oscilloscope channel number
            tipo_misura: Type of measurement
            bucket_interval: Time bucket interval for downsampling (e.g., '100 microseconds', '1 millisecond')
            
        Returns:
            List of downsampled waveform data
        """
        try:
            # Convert interval string to PostgreSQL interval format
            query = """
                SELECT 
                    date_bin(%s::INTERVAL, timestamp_campione, TIMESTAMP '2000-01-01') AS timestamp_bucket,
                    canale,
                    tipo_misura,
                    AVG(valore) AS valore_medio,
                    MIN(valore) AS valore_min,
                    MAX(valore) AS valore_max,
                    COUNT(*) AS num_campioni
                FROM forme_d_onda 
                WHERE id_punto = %s AND canale = %s AND tipo_misura = %s
                GROUP BY timestamp_bucket, canale, tipo_misura
                ORDER BY timestamp_bucket;
            """
            params = (bucket_interval, id_punto, canale, tipo_misura)
            
            results = self.db.execute_query(query, params, fetch_results=True)
            if results:
                self.logger.debug(f"Retrieved {len(results)} downsampled buckets for point {id_punto}")
            
            return results if results else []
            
        except Exception as e:
            self.logger.error(f"Failed to get downsampled waveform data: {str(e)}")
            return []
    
    def delete_waveform_data(self, id_punto: int) -> bool:
        """
        Delete all waveform data for a measurement point.
        
        Args:
            id_punto: Measurement point ID
            
        Returns:
            bool: True if deletion successful
        """
        try:
            query = "DELETE FROM forme_d_onda WHERE id_punto = %s;"
            self.db.execute_query(query, (id_punto,), fetch_results=False)
            
            # Update measurement point flag
            update_query = "UPDATE punti_misura SET ha_forma_onda = FALSE WHERE id_punto = %s;"
            self.db.execute_query(update_query, (id_punto,), fetch_results=False)
            
            self.logger.info(f"Deleted waveform data for measurement point {id_punto}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to delete waveform data: {str(e)}")
            return False


class DatabaseQueries:
    """
    Collection of complex queries for data analysis and visualization.
    Provides high-level query methods for common analysis tasks.
    """
    
    def __init__(self, db_manager: DatabaseManager):
        """
        Initialize DatabaseQueries with database manager.
        
        Args:
            db_manager: DatabaseManager instance for database operations
        """
        self.db = db_manager
        self.logger = Logger()
    
    def get_efficiency_map(self, session_id: int) -> List[Dict[str, Any]]:
        """
        Get efficiency map for a sweep session.
        
        Args:
            session_id: Sweep session ID
            
        Returns:
            List of efficiency data points
        """
        try:
            query = """
                SELECT 
                    vin_target,
                    iout_target,
                    efficienza,
                    temperatura,
                    potenza_out,
                    timestamp_misura
                FROM punti_misura pm 
                JOIN sessioni_sweep ss ON pm.id_sessione = ss.id_sessione
                WHERE ss.id_sessione = %s
                    AND efficienza IS NOT NULL
                ORDER BY vin_target, iout_target;
            """
            
            results = self.db.execute_query(query, (session_id,), fetch_results=True)
            return results if results else []
            
        except Exception as e:
            self.logger.error(f"Failed to get efficiency map: {str(e)}")
            return []
    
    def get_worst_efficiency_point_with_waveform(self, session_id: int) -> Dict[str, Any]:
        """
        Find measurement point with lowest efficiency that has waveform data.
        
        Args:
            session_id: Sweep session ID
            
        Returns:
            Dictionary containing point data and waveform samples
        """
        try:
            # Find point with minimum efficiency
            point_query = """
                SELECT 
                    pm.id_punto,
                    pm.vin_target,
                    pm.iout_target,
                    pm.efficienza,
                    pm.timestamp_misura
                FROM punti_misura pm
                JOIN sessioni_sweep ss ON pm.id_sessione = ss.id_sessione  
                WHERE ss.id_sessione = %s
                    AND pm.efficienza IS NOT NULL
                    AND pm.ha_forma_onda = TRUE
                ORDER BY pm.efficienza ASC
                LIMIT 1;
            """
            
            point_results = self.db.execute_query(point_query, (session_id,), fetch_results=True)
            if not point_results:
                return {}
            
            point = point_results[0]
            
            # Get waveform data for this point
            waveform_query = """
                SELECT 
                    canale,
                    tipo_misura,
                    timestamp_campione,
                    valore,
                    indice_campione
                FROM forme_d_onda 
                WHERE id_punto = %s
                ORDER BY canale, tipo_misura, indice_campione;
            """
            
            waveform_results = self.db.execute_query(waveform_query, (point['id_punto'],), fetch_results=True)
            
            return {
                'measurement_point': point,
                'waveform_data': waveform_results if waveform_results else []
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get worst efficiency point with waveform: {str(e)}")
            return {}
    
    def get_session_summary(self, session_id: int) -> Dict[str, Any]:
        """
        Get comprehensive summary of a sweep session.
        
        Args:
            session_id: Sweep session ID
            
        Returns:
            Dictionary containing session summary statistics
        """
        try:
            query = """
                SELECT 
                    ss.nome_sessione,
                    ss.data_inizio,
                    ss.data_fine,
                    ss.stato_sessione,
                    COUNT(pm.id_punto) as total_points,
                    COUNT(CASE WHEN pm.efficienza IS NOT NULL THEN 1 END) as measured_points,
                    COUNT(CASE WHEN pm.ha_forma_onda = TRUE THEN 1 END) as points_with_waveforms,
                    AVG(pm.efficienza) as avg_efficiency,
                    MIN(pm.efficienza) as min_efficiency,
                    MAX(pm.efficienza) as max_efficiency,
                    AVG(pm.temperatura) as avg_temperature
                FROM sessioni_sweep ss
                LEFT JOIN punti_misura pm ON ss.id_sessione = pm.id_sessione
                WHERE ss.id_sessione = %s
                GROUP BY ss.id_sessione, ss.nome_sessione, ss.data_inizio, 
                         ss.data_fine, ss.stato_sessione;
            """
            
            results = self.db.execute_query(query, (session_id,), fetch_results=True)
            return results[0] if results else {}
            
        except Exception as e:
            self.logger.error(f"Failed to get session summary: {str(e)}")
            return {}