"""
Database management module for Lab Automation PostgreSQL/TimescaleDB integration.

This module provides connection management, schema creation, and data access
operations for the DC-DC converter measurement system.
"""

import psycopg2
import psycopg2.extras
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from typing import Optional, Dict, List, Any, Tuple
import logging
from contextlib import contextmanager
import json
from datetime import datetime
from logger import Logger


class DatabaseManager:
    """
    Main database manager class for PostgreSQL/TimescaleDB operations.
    Handles connection management, schema operations, and provides base functionality
    for data access operations.
    """
    
    def __init__(self, host: str = 'localhost', port: int = 5432, 
                 database: str = 'dcdc_measurements', username: str = 'dcdc_app', 
                 password: str = '', **kwargs):
        """
        Initialize database manager with connection parameters.
        
        Args:
            host: Database host address
            port: Database port number
            database: Database name
            username: Database username
            password: Database password
            **kwargs: Additional connection parameters
        """
        self.connection_params = {
            'host': host,
            'port': port,
            'database': database,
            'user': username,
            'password': password,
            **kwargs
        }
        self.logger = Logger()
        self._connection = None
        self._schema_initialized = False
    
    @contextmanager
    def get_connection(self):
        """
        Context manager for database connections with automatic cleanup.
        
        Yields:
            psycopg2.connection: Database connection object
        """
        conn = None
        try:
            conn = psycopg2.connect(**self.connection_params)
            self.logger.debug(f"Database connection established to {self.connection_params['host']}:{self.connection_params['port']}")
            yield conn
        except psycopg2.Error as e:
            self.logger.error(f"Database connection error: {str(e)}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()
                self.logger.debug("Database connection closed")
    
    def test_connection(self) -> bool:
        """
        Test database connectivity and TimescaleDB extension availability.
        
        Returns:
            bool: True if connection successful and TimescaleDB available
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Test basic connection
                    cursor.execute("SELECT version();")
                    version = cursor.fetchone()[0]
                    self.logger.info(f"Connected to PostgreSQL: {version}")
                    
                    # Check TimescaleDB extension
                    cursor.execute("""
                        SELECT default_version, installed_version 
                        FROM pg_available_extensions 
                        WHERE name = 'timescaledb';
                    """)
                    result = cursor.fetchone()
                    if result:
                        default_ver, installed_ver = result
                        if installed_ver:
                            self.logger.info(f"TimescaleDB extension active: {installed_ver}")
                        else:
                            self.logger.warning("TimescaleDB extension available but not installed")
                    else:
                        self.logger.error("TimescaleDB extension not available")
                        return False
                    
                    return True
        except Exception as e:
            self.logger.error(f"Connection test failed: {str(e)}")
            return False
    
    def initialize_database(self) -> bool:
        """
        Initialize database with TimescaleDB extension and create schema.
        
        Returns:
            bool: True if initialization successful
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Enable TimescaleDB extension
                    cursor.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")
                    self.logger.info("TimescaleDB extension enabled")
                    
                    # Create schema
                    if self._create_schema(cursor):
                        conn.commit()
                        self._schema_initialized = True
                        self.logger.info("Database schema created successfully")
                        return True
                    else:
                        conn.rollback()
                        return False
                        
        except Exception as e:
            self.logger.error(f"Database initialization failed: {str(e)}")
            return False
    
    def _create_schema(self, cursor) -> bool:
        """
        Create all database tables and indexes.
        
        Args:
            cursor: Database cursor object
            
        Returns:
            bool: True if schema creation successful
        """
        try:
            # Create progetti table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS progetti (
                    id_progetto SERIAL PRIMARY KEY,
                    nome_progetto VARCHAR(255) NOT NULL UNIQUE,
                    descrizione TEXT,
                    data_creazione TIMESTAMPTZ DEFAULT NOW(),
                    data_modifica TIMESTAMPTZ DEFAULT NOW(),
                    parametri_globali JSONB,
                    CONSTRAINT nome_progetto_not_empty CHECK (LENGTH(TRIM(nome_progetto)) > 0)
                );
            """)
            self.logger.debug("Created progetti table")
            
            # Create sessioni_sweep table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessioni_sweep (
                    id_sessione SERIAL PRIMARY KEY,
                    id_progetto INTEGER NOT NULL,
                    nome_sessione VARCHAR(255) NOT NULL,
                    data_inizio TIMESTAMPTZ DEFAULT NOW(),
                    data_fine TIMESTAMPTZ,
                    valori_vin NUMERIC(10,4)[] NOT NULL,
                    valori_iout NUMERIC(10,6)[] NOT NULL,
                    stato_sessione VARCHAR(50) DEFAULT 'in_corso',
                    note TEXT,
                    FOREIGN KEY (id_progetto) REFERENCES progetti(id_progetto) ON DELETE CASCADE,
                    CONSTRAINT valori_arrays_not_empty CHECK (
                        array_length(valori_vin, 1) > 0 AND 
                        array_length(valori_iout, 1) > 0
                    )
                );
            """)
            self.logger.debug("Created sessioni_sweep table")
            
            # Create punti_misura table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS punti_misura (
                    id_punto SERIAL PRIMARY KEY,
                    id_sessione INTEGER NOT NULL,
                    vin_target NUMERIC(10,4) NOT NULL,
                    iout_target NUMERIC(10,6) NOT NULL,
                    timestamp_misura TIMESTAMPTZ DEFAULT NOW(),
                    vin_reale NUMERIC(10,4),
                    vout_reale NUMERIC(10,4),
                    iout_reale NUMERIC(10,6),
                    iin_reale NUMERIC(10,6),
                    efficienza NUMERIC(6,4),
                    temperatura NUMERIC(6,2),
                    potenza_in NUMERIC(12,6),
                    potenza_out NUMERIC(12,6),
                    ha_forma_onda BOOLEAN DEFAULT FALSE,
                    note_punto TEXT,
                    FOREIGN KEY (id_sessione) REFERENCES sessioni_sweep(id_sessione) ON DELETE CASCADE,
                    CONSTRAINT efficienza_range CHECK (efficienza >= 0 AND efficienza <= 100),
                    CONSTRAINT potenze_positive CHECK (potenza_in >= 0 AND potenza_out >= 0)
                );
            """)
            self.logger.debug("Created punti_misura table")
            
            # Create forme_d_onda table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS forme_d_onda (
                    timestamp_campione TIMESTAMPTZ NOT NULL,
                    id_punto INTEGER NOT NULL,
                    canale INTEGER NOT NULL,
                    tipo_misura VARCHAR(50) NOT NULL,
                    valore NUMERIC(15,9) NOT NULL,
                    indice_campione BIGINT NOT NULL,
                    frequenza_campionamento NUMERIC(12,3),
                    risoluzione_verticale NUMERIC(12,9),
                    FOREIGN KEY (id_punto) REFERENCES punti_misura(id_punto) ON DELETE CASCADE
                );
            """)
            self.logger.debug("Created forme_d_onda table")
            
            # Check if hypertable already exists
            cursor.execute("""
                SELECT 1 FROM timescaledb_information.hypertables 
                WHERE hypertable_name = 'forme_d_onda';
            """)
            if not cursor.fetchone():
                # Create hypertable
                cursor.execute("""
                    SELECT create_hypertable('forme_d_onda', 'timestamp_campione', 
                                            chunk_time_interval => INTERVAL '1 hour',
                                            if_not_exists => TRUE);
                """)
                self.logger.debug("Created forme_d_onda hypertable")
            
            # Create indexes for optimization
            self._create_indexes(cursor)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Schema creation failed: {str(e)}")
            return False
    
    def _create_indexes(self, cursor):
        """
        Create database indexes for query optimization.
        
        Args:
            cursor: Database cursor object
        """
        indexes = [
            # Progetti indexes
            "CREATE INDEX IF NOT EXISTS idx_progetti_nome ON progetti(nome_progetto);",
            "CREATE INDEX IF NOT EXISTS idx_progetti_data_creazione ON progetti(data_creazione);",
            
            # Sessioni_sweep indexes
            "CREATE INDEX IF NOT EXISTS idx_sessioni_progetto ON sessioni_sweep(id_progetto);",
            "CREATE INDEX IF NOT EXISTS idx_sessioni_data_inizio ON sessioni_sweep(data_inizio);",
            "CREATE INDEX IF NOT EXISTS idx_sessioni_stato ON sessioni_sweep(stato_sessione);",
            
            # Punti_misura indexes
            "CREATE INDEX IF NOT EXISTS idx_punti_sessione ON punti_misura(id_sessione);",
            "CREATE INDEX IF NOT EXISTS idx_punti_timestamp ON punti_misura(timestamp_misura);",
            "CREATE INDEX IF NOT EXISTS idx_punti_target ON punti_misura(vin_target, iout_target);",
            "CREATE INDEX IF NOT EXISTS idx_punti_efficienza ON punti_misura(efficienza DESC);",
            
            # Forme_d_onda indexes
            "CREATE INDEX IF NOT EXISTS idx_forme_punto ON forme_d_onda(id_punto, timestamp_campione);",
            "CREATE INDEX IF NOT EXISTS idx_forme_canale_tipo ON forme_d_onda(canale, tipo_misura);"
        ]
        
        for index_sql in indexes:
            try:
                cursor.execute(index_sql)
            except Exception as e:
                self.logger.warning(f"Index creation warning: {str(e)}")
        
        self.logger.debug("Database indexes created")
    
    def execute_query(self, query: str, params: Optional[Tuple] = None, 
                     fetch_results: bool = True) -> Optional[List[Any]]:
        """
        Execute a SQL query and return results.
        
        Args:
            query: SQL query string
            params: Query parameters tuple
            fetch_results: Whether to fetch and return results
            
        Returns:
            List of query results or None
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    cursor.execute(query, params)
                    
                    if fetch_results:
                        results = cursor.fetchall()
                        self.logger.debug(f"Query executed successfully, returned {len(results)} rows")
                        return results
                    else:
                        conn.commit()
                        self.logger.debug("Query executed successfully (no results)")
                        return None
                        
        except Exception as e:
            self.logger.error(f"Query execution failed: {str(e)}")
            raise
    
    def execute_many(self, query: str, params_list: List[Tuple]) -> bool:
        """
        Execute a query multiple times with different parameters (bulk operation).
        
        Args:
            query: SQL query string
            params_list: List of parameter tuples
            
        Returns:
            bool: True if execution successful
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.executemany(query, params_list)
                    conn.commit()
                    self.logger.debug(f"Bulk query executed successfully for {len(params_list)} records")
                    return True
                    
        except Exception as e:
            self.logger.error(f"Bulk query execution failed: {str(e)}")
            return False
    
    def get_schema_info(self) -> Dict[str, Any]:
        """
        Get information about the current database schema.
        
        Returns:
            Dictionary containing schema information
        """
        try:
            with self.get_connection() as conn:
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
                    # Get table information
                    cursor.execute("""
                        SELECT table_name, table_type 
                        FROM information_schema.tables 
                        WHERE table_schema = 'public' 
                        ORDER BY table_name;
                    """)
                    tables = cursor.fetchall()
                    
                    # Get hypertable information
                    cursor.execute("""
                        SELECT hypertable_name, associated_schema_name, num_dimensions
                        FROM timescaledb_information.hypertables;
                    """)
                    hypertables = cursor.fetchall()
                    
                    return {
                        'tables': tables,
                        'hypertables': hypertables,
                        'connection_params': {k: v for k, v in self.connection_params.items() if k != 'password'}
                    }
                    
        except Exception as e:
            self.logger.error(f"Failed to get schema info: {str(e)}")
            return {}