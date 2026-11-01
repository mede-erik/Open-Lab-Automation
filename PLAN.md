# PLAN – Open Lab Automation come piattaforma di misura generica

Stato: **bozza** (2026-11-01). I punti marcati ❓ sono ancora da decidere.

## 1. Obiettivo

Passare da "strumenti da remoto + una misura di efficienza" a un software
generico in cui:

- un **progetto** contiene **più misure** di tipo diverso (es. progetto "Pippo":
  efficienza + risposta al transitorio + ripple);
- ogni misura ha **un proprio file** con estensione dipendente dal tipo;
- le misure sono **moduli**: alcuni integrati, altri scritti dall'utente;
- l'efficienza resta la misura di riferimento (il progetto nasce per quella),
  ma oggi **non è ancora validata su hardware** → va provata, non solo portata.

Decisioni già prese:

- **Nessuna retrocompatibilità** con i vecchi `.eff` / `.was` / progetti esistenti
  (il software non è ancora in uso). Si può cambiare formato liberamente.
- Architettura modulare: moduli base integrati + moduli utente.

## 2. Vocabolario

```
Progetto ─┬─ Strumenti (.inst)             ← condivisi da tutte le misure
          ├─ Misura "Efficienza"   (.eff)  ┐
          ├─ Misura "Transitorio"  (.ltr)  ├─ ognuna = istanza di un Tipo di misura (modulo)
          └─ Misura "Ripple"       (.rpl)  ┘
                 └─ Run (esecuzione) ─ Punti / Forme d'onda / Tracce
```

- **Tipo di misura** = un modulo (codice + schema parametri + editor).
- **Misura** = istanza configurata di un tipo, salvata in un suo file.
- **Run** = una singola esecuzione di una misura, con i dati prodotti.

## 3. Formato progetto (nuovo)

Il JSON di progetto sostituisce le liste `eff_files`/`was_files` con:

```json
{
  "project_name": "Pippo",
  "inst_file": "pippo.inst",
  "measurements": [
    {"id": "m1", "type": "efficiency",     "name": "Efficienza",  "file": "efficienza.eff"},
    {"id": "m2", "type": "load_transient", "name": "Transitorio", "file": "transitorio.ltr"}
  ]
}
```

Ogni file di misura ha un'intestazione comune
(`type`, `module_version`, `api_version`, `role_bindings`) e un corpo `params`
definito dal modulo. Le `control_variables`/`measure_variables` globali di oggi
passano a essere responsabilità della singola misura.

## 4. Sistema a moduli

### 4.1 Struttura di un modulo

```
mymodule/
  module.json     # manifest: id, nome, versione, api_version, estensione file,
                  #           ruoli strumento richiesti, dipendenze Python
  measurement.py  # classe che implementa l'interfaccia Measurement
  schema.json     # schema dei parametri → editor generato automaticamente
  editor.py       # (opzionale) editor Qt custom
```

Posizioni di ricerca:

1. `frontend/measurements/builtin/` – moduli integrati;
2. cartella utente (es. `~/.open_lab_automation/modules/`);
3. `modules/` dentro il progetto (moduli specifici di quel progetto).

### 4.2 Interfaccia `Measurement`

```python
class Measurement:
    required_roles: dict[str, Capability]   # es. {"generator": "awg", "scope": "scope"}
    def validate(self, params, bound_instruments) -> list[ValidationError]
    def setup(self, ctx)            # configura strumenti, stato sicuro iniziale
    def run(self, ctx)              # loop della misura; usa ctx.emit_point / ctx.emit_trace,
                                    # controlla ctx.should_stop() / ctx.pause_point()
    def teardown(self, ctx)         # SEMPRE chiamato: riporta gli strumenti in stato sicuro
    def derived(self, data)         # grandezze calcolate (efficienza, ecc.)
```

Il `ctx` (contesto) è fornito dal framework: accesso agli strumenti, emissione
dati, progresso, log, cancellazione. Il modulo **non** apre finestre né scrive
file direttamente.

### 4.3 Ruoli e capability (il punto chiave)

Una misura non dice "usa il Keysight 34972A": dice "mi serve un *generatore
di funzioni*, un *oscilloscopio*". L'utente associa i ruoli agli strumenti del
`.inst`. Gli strumenti dichiarano le **capability** nella libreria (es.
`awg`, `scope`, `dmm`, `psu`, `eload`, `spectrum`, `vna`, `power_meter`), con
i comandi SCPI definiti dalla libreria, come già avviene oggi.
Così lo stesso modulo funziona con strumenti diversi e un nuovo strumento si
aggiunge solo estendendo la libreria.

### 4.4 Sicurezza dei moduli utente

Un modulo utente è codice Python arbitrario che pilota hardware: va
dichiarato esplicitamente (avviso al primo caricamento, elenco in
Impostazioni, possibilità di disabilitarli). Il framework garantisce
`teardown()` anche in caso di errore/stop, e i limiti di sicurezza degli
strumenti (max V/I/P dalla libreria) sono applicati nel livello strumenti,
non lasciati al modulo.

### 4.5 UI

- Dialog "Aggiungi misura" che elenca i tipi disponibili.
- Editor generico generato dallo `schema.json` (campi, range, unità, validazione).
- Pannello **Run** unico per tutti i tipi: avvio/stop/pausa, progresso,
  grafico live, tabella dati, export.

## 5. Misure previste

| # | Misura | Strumenti (ruoli) | Note |
|---|--------|-------------------|------|
| 1 | **Efficienza** (integrata) | PSU/sorgente, eload, DMM/datalogger (o power meter) | Sweep annidato come oggi. **Da validare su hardware.** |
| 2 | **Diagramma di Bode** | AWG + scope, oppure VNA | Sweep di frequenza, guadagno/fase. Con iniezione per loop gain; modalità VNA diretta. |
| 3 | **Ripple e rumore** | Scope (opz. spectrum analyzer) | Banda limitata 20 MHz, p-p, RMS, spettro del ripple. |
| 4 | **Logging nel tempo** | Datalogger/DMM/termocoppie | Più canali, intervallo configurabile, scrittura incrementale, grafico live. |
| 5 | **Risposta al transitorio di carico** | Eload (dinamico) + scope | Riusa la logica del Pulse Generator; misura overshoot/undershoot e tempo di assestamento. |
| 6 | Spettro / emissioni | Spectrum analyzer | Tracce, marker, peak search. |
| 7 | Analisi di rete (S-param) | VNA | S11/S21, export Touchstone. |

Candidate successive (a basso costo, riusano gli stessi mattoni): regolazione
di linea e di carico, PSRR, impedenza di uscita, curva I-V, sequenza di
accensione/spegnimento, curva di derating termico.

## 6. Nuovi strumenti da aggiungere alla libreria

Priorità alta (servono alle misure 2–7):

- **Generatore di funzioni / AWG** – indispensabile per Bode e transitori.
- **Spectrum analyzer** (richiesto).
- **VNA** (richiesto).

Priorità media:

- **Multimetro da banco (DMM)** a sé stante, oltre al datalogger.
- **Power meter / power analyzer** (Yokogawa WT, ecc.): misura di potenza vera
  per un'efficienza più accurata, soprattutto lato AC/forme d'onda distorte.
- **Source-Measure Unit (SMU)**: curve I-V, caratterizzazione.
- **Camera climatica / forno**: logging termico e derating con temperatura controllata.

Priorità bassa / futuro:

- **LCR meter / impedance analyzer** (caratterizzazione di condensatori e induttori).
- **Sorgente AC programmabile**.
- **Frequenzimetro / contatore**.
- **Matrice di relè / multiplexer** (più punti di misura con un solo strumento).

Ogni strumento nuovo richiede: tipo + capability nella libreria, comandi SCPI
nel JSON, dialog di configurazione e (se serve) estensione dell'editor `.inst`.

## 7. Dati

- Modello `Run` generico (rinomina di `SweepSession`), con:
  `run_id`, `measurement_id`, `started_at`, parametri usati (snapshot),
  strumenti usati.
- Tre tipi di dato oltre ai punti scalari: **serie temporali**, **forme
  d'onda/tracce** (scope, spectrum), **dati complessi** (VNA, Bode).
- Salvataggio incrementale durante la run (un crash non perde tutto).
- Export CSV in ogni caso; altri formati (Touchstone, xlsx) per modulo.
- Grandezze derivate come formule tra variabili (es. `eta = Pout/Pin`).

## 8. Fasi di sviluppo

**Fase 0 – Base**
- Test di regressione sull'attuale pipeline dell'efficienza (con strumenti simulati).
- Livello strumenti "simulato" (mock) per sviluppare e testare senza hardware.

**Fase 1 – Core**
- Nuovo formato progetto (`measurements[]`), nuovo `ProjectDatabaseManager`.
- Interfaccia `Measurement`, `Capability`, contesto di esecuzione, runner in thread.
- Modello `Run` generico.

**Fase 2 – Moduli**
- Registro/loader dei moduli (integrati + utente + progetto) con manifest.
- Editor generico da `schema.json`.
- Efficienza riscritta come primo modulo integrato.
- Pannello Run unico (live, stop/pausa, export).

**Fase 3 – Prime nuove misure**
- Logging nel tempo (la più semplice: valida il runner e i dati temporali).
- Ripple e rumore.
- Strumento AWG nella libreria → Bode (con scope).
- Transitorio di carico.

**Fase 4 – Strumenti avanzati**
- Spectrum analyzer, VNA, relative misure (6, 7).
- Bode via VNA.

**Fase 5 – Rifinitura**
- Documentazione per scrivere un modulo (con modulo di esempio).
- Confronto tra run, report, formule derivate.
- Validazione dell'efficienza su hardware reale.

## 9. Punti aperti

- ❓ **Backend C**: raccomandato spostare l'orchestrazione in Python e tenere il
  C solo per l'I/O sugli strumenti (`sweep.c` verrebbe rimosso). Da confermare.
- ❓ **Estensioni file**: `.eff` resta per l'efficienza; scegliere le altre
  (proposta: una per tipo, `.bode`, `.rpl`, `.ltr`, `.log`) oppure un'unica
  estensione `.meas` con il tipo nell'intestazione.
- ❓ **Libreria strumenti**: il sottomodulo `Instruments_LIB` va esteso con le
  nuove capability; vive in un repo separato (`instruments_lib`), quindi le
  modifiche andranno coordinate tra i due repo.
- ❓ **Moduli utente**: solo Python, o anche eseguibili esterni/altri linguaggi?
  Proposta: solo Python nella prima versione.
- ❓ **Lingue**: ogni modulo porta le proprie traduzioni, o usa solo le chiavi
  del core? Proposta: i moduli portano un proprio `lang/` opzionale.
