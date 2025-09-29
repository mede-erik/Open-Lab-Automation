#TODO rebuild all

-- ### Fase 1: Setup del Database e dell'Utente ⚙️

-- Crea l'utente dell'applicazione
CREATE USER labauto_app WITH PASSWORD 'labauto_password_secure';

-- Crea il database dedicato
CREATE DATABASE labauto_measurements;

-- Assegna la proprietà del database all'utente
ALTER DATABASE labauto_measurements OWNER TO labauto_app;

-- Connettiti al database
\c labauto_measurements

-- Abilita l'estensione TimescaleDB
CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ### Fase 2: Creazione dello Schema (Tabelle) 🏗️

-- Tabella dei progetti
CREATE TABLE progetti (
    id_progetto SERIAL PRIMARY KEY,
    nome VARCHAR(100) UNIQUE NOT NULL,
    descrizione TEXT,
    data_creazione TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    data_modifica TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- Tabella delle sessioni di sweep
CREATE TABLE sessioni_sweep (
    id_sessione SERIAL PRIMARY KEY,
    id_progetto INTEGER REFERENCES progetti(id_progetto) ON DELETE CASCADE,
    nome VARCHAR(100) NOT NULL,
    data_inizio TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    data_fine TIMESTAMPTZ,
    -- Array di punti di sweep come array numerici
    vin_array NUMERIC[] NOT NULL, -- Array delle tensioni di ingresso
    iout_array NUMERIC[] NOT NULL, -- Array delle correnti di carico
    note TEXT,
    UNIQUE(id_progetto, nome)
);

-- Tabella dei punti di misura
CREATE TABLE punti_misura (
    id_punto SERIAL PRIMARY KEY,
    id_sessione INTEGER REFERENCES sessioni_sweep(id_sessione) ON DELETE CASCADE,
    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    vin_target NUMERIC(10,3) NOT NULL, -- Tensione di ingresso target
    iout_target NUMERIC(10,3) NOT NULL, -- Corrente di carico target
    vin_reale NUMERIC(10,3), -- Tensione di ingresso misurata
    iin_reale NUMERIC(10,3), -- Corrente di ingresso misurata
    vout_reale NUMERIC(10,3), -- Tensione di uscita misurata
    iout_reale NUMERIC(10,3), -- Corrente di uscita misurata
    temperatura NUMERIC(5,2), -- Temperatura in °C
    efficienza NUMERIC(6,3), -- Efficienza calcolata (0-100%)
    pin NUMERIC(10,3), -- Potenza di ingresso calcolata
    pout NUMERIC(10,3), -- Potenza di uscita calcolata
    note TEXT
);

-- Tabella delle forme d'onda
CREATE TABLE forme_d_onda (
    id_forma SERIAL,
    id_punto INTEGER REFERENCES punti_misura(id_punto) ON DELETE CASCADE,
    timestamp TIMESTAMPTZ NOT NULL, -- Timestamp del campione
    canale INTEGER NOT NULL, -- Numero del canale dell'oscilloscopio
    valore DOUBLE PRECISION NOT NULL, -- Valore del campione
    PRIMARY KEY (id_forma, timestamp)
);

-- Trasforma la tabella forme_d_onda in una hypertable
SELECT create_hypertable('forme_d_onda', 'timestamp');

-- Indici per ottimizzare le query più comuni
CREATE INDEX idx_progetti_nome ON progetti(nome);
CREATE INDEX idx_sessioni_data ON sessioni_sweep(data_inizio);
CREATE INDEX idx_punti_efficienza ON punti_misura(efficienza);
CREATE INDEX idx_punti_sessione_timestamp ON punti_misura(id_sessione, timestamp);
CREATE INDEX idx_forme_punto_canale ON forme_d_onda(id_punto, canale);


