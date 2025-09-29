-- ### Fase 1: Setup del Database e dell'Utente ⚙️

-- Crea l'utente dell'applicazione
CREATE USER dcdc_app WITH PASSWORD 'dcdc_password_secure';

-- Crea il database dedicato
CREATE DATABASE dcdc_measurements;

-- Assegna la proprietà del database all'utente
ALTER DATABASE dcdc_measurements OWNER TO dcdc_app;

-- Connettiti al database
\c dcdc_measurements

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

-- ### Fase 3: Esempio di Inserimento Dati ✍️

-- Inserimento di un nuovo progetto
INSERT INTO progetti (nome, descrizione) 
VALUES ('Convertitore Buck 12V', 'Test di efficienza convertitore buck 12V->5V') 
RETURNING id_progetto;

-- Inserimento di una sessione di sweep
INSERT INTO sessioni_sweep (id_progetto, nome, vin_array, iout_array, note)
VALUES (
    1, -- id_progetto restituito dall'insert precedente
    'Sweep Completo',
    ARRAY[10.0, 11.0, 12.0, 13.0, 14.0]::NUMERIC[], -- punti Vin
    ARRAY[0.1, 0.5, 1.0, 2.0, 3.0]::NUMERIC[], -- punti Iout
    'Sweep completo con 25 punti di misura'
) RETURNING id_sessione;

-- Inserimento di un punto di misura
INSERT INTO punti_misura (
    id_sessione, vin_target, iout_target, 
    vin_reale, iin_reale, vout_reale, iout_reale,
    temperatura, efficienza, pin, pout
)
VALUES (
    1, -- id_sessione restituito dall'insert precedente
    12.0, 1.0, -- target
    12.05, 0.45, 5.02, 0.98, -- valori reali
    35.2, 90.5, -- temperatura ed efficienza
    12.05 * 0.45, 5.02 * 0.98 -- pin e pout
) RETURNING id_punto;

-- Inserimento bulk di forme d'onda (esempio con 1000 punti)
INSERT INTO forme_d_onda (id_punto, timestamp, canale, valore)
SELECT 
    1, -- id_punto restituito dall'insert precedente
    '2025-08-08 10:00:00'::TIMESTAMPTZ + (n || ' microseconds')::INTERVAL,
    1, -- canale
    sin(n::float/100) -- valore simulato
FROM generate_series(0, 999) n;

-- ### Fase 4: Query di Esempio 📊

-- Query 1: Mappa di efficienza per una sessione
SELECT 
    vin_target,
    iout_target,
    efficienza,
    temperatura
FROM punti_misura
WHERE id_sessione = 1
ORDER BY vin_target, iout_target;

-- Query 2: Forma d'onda del punto con efficienza minima
WITH punto_min_eff AS (
    SELECT id_punto
    FROM punti_misura
    WHERE id_sessione = 1
    ORDER BY efficienza ASC
    LIMIT 1
)
SELECT f.timestamp, f.canale, f.valore, p.efficienza
FROM forme_d_onda f
JOIN punto_min_eff pme ON f.id_punto = pme.id_punto
JOIN punti_misura p ON p.id_punto = pme.id_punto
WHERE f.timestamp BETWEEN 
    '2025-08-08 10:00:00'::TIMESTAMPTZ AND 
    '2025-08-08 10:00:01'::TIMESTAMPTZ
ORDER BY f.timestamp;

-- Query 3: Downsampling di una forma d'onda per visualizzazione
SELECT 
    time_bucket('100 microseconds', timestamp) AS bucket,
    canale,
    avg(valore) as valore_medio,
    min(valore) as valore_min,
    max(valore) as valore_max
FROM forme_d_onda
WHERE 
    id_punto = 1 AND
    timestamp BETWEEN 
        '2025-08-08 10:00:00'::TIMESTAMPTZ AND 
        '2025-08-08 10:00:01'::TIMESTAMPTZ
GROUP BY bucket, canale
ORDER BY bucket;
