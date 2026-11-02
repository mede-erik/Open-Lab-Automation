# PLAN – Open Lab Automation come piattaforma di misura generica

Stato: **bozza** (2026-11-02). I punti marcati ❓ sono ancora da decidere.

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
- **Un'estensione file per ogni tipo di misura** (facile da riconoscere, copiare, eliminare).
- **Latenza minima**: valutata con un benchmark (vedi §4); orchestrazione in Python,
  strato nativo (Rust) per il trasporto.
- **I moduli non parlano mai SCPI**: chiedono azioni a uno strumento generico
  ("alimentatore → 20 V, ON") e il software le traduce nei comandi corretti,
  con controllo dei limiti (§5).

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

## 4. Latenza e architettura a livelli

### 4.1 Misura sul codice attuale (loopback, finto strumento SCPI, 300 query)

| Implementazione | Mediana | Max |
|---|---|---|
| Backend C attuale (`send` comando + `send` "\n", senza `TCP_NODELAY`) | **44 000 µs** | 67 ms |
| Python puro, stesso schema (2 `send`, senza `TCP_NODELAY`) | **44 000 µs** | 72 ms |
| Python puro, 1 `send` + `TCP_NODELAY` | **32 µs** | 0,7 ms |

Conclusioni:

1. Il collo di bottiglia **non è il linguaggio**: C e Python danno lo stesso risultato.
   Il costo è la combinazione Nagle + ACK ritardato, che aggiunge ~44 ms a ogni
   query. È un bug del backend attuale (`instrument_send` fa due `send` e manca
   `TCP_NODELAY`): correggendolo si guadagna un fattore ~1000.
2. Con il trasporto corretto l'overhead di Python è di decine di µs. Su uno strumento
   reale una query costa 1–50 ms (rete + tempo di misura/NPLC): il linguaggio dell'host
   incide per meno dell'1 %.
3. Dove il linguaggio conta davvero: **jitter** (GIL, thread della GUI, GC) quando due
   azioni devono avvenire a distanza temporale controllata, e **throughput** nello
   streaming/logging veloce. Per queste serve codice nativo con thread proprio,
   senza GIL. Per la sincronizzazione vera la soluzione migliore resta comunque
   **delegare allo strumento** (trigger hardware, buffer, list mode), non all'host.
4. Il backend C attuale fa solo TCP raw: USB, GPIB e seriale (citati nel README) non
   esistono nel backend, e i comandi SCPI del sweep sono hardcoded invece di venire
   dalla libreria. Lo stato è globale e non thread-safe.

### 4.2 Scelta: ibrido Python + Rust (✅ deciso)

| Livello | Linguaggio | Compito |
|---|---|---|
| Moduli di misura, runner, UI | Python | Logica della misura, nessun vincolo di tempo stretto |
| Strumento generico + traduzione SCPI + limiti | Python (prima versione) | Guidato dalla libreria, facile da estendere |
| Trasporto (TCP/LXI, poi USB, seriale, GPIB/VISA) | **Rust** | `TCP_NODELAY`, un solo write, letture bufferizzate, timeout, thread-safe |
| Esecutore di sequenze | **Rust**, *non previsto* (vedi §4.3) | Sequenza compilata eseguita in un thread nativo senza GIL; da riconsiderare solo se emerge un caso reale |

Perché Rust invece di C: il codice C esistente è poco (≈430 righe) e va comunque
riscritto; Rust dà sicurezza di memoria e thread, crate pronte per seriale/USB, e
wheel precompilate (maturin/PyO3) che evitano all'utente di installare un compilatore
(oggi serve `gcc`). Costo: i contributori devono saper leggere Rust.
Il backend C esistente verrà sostituito dal trasporto Rust (`backend/` rimosso a
migrazione finita); fino ad allora resta in uso.

Fino a quando il livello nativo non c'è, il trasporto può essere Python (`socket`
con `TCP_NODELAY`, o `pyvisa` per USB/GPIB). L'interfaccia `Transport` è unica, quindi
la sostituzione è trasparente per i moduli.

### 4.3 Caso critico: test a impulsi di carico

L'unico caso con timing stretto, per ora, è il test di impulsi/step di carico
(modulo transitorio, `.ltr`, e Pulse Generator). Ragionamento:

- L'impulso **non lo genera l'host**: il carico elettronico lo produce internamente
  (modo dinamico: livelli, frequenza, duty, rise/fall). L'host non deve commutare
  nulla a tempo, quindi il jitter di Python non incide sulla forma dell'impulso.
- Il timing che conta è tra **carico e scope**. Si ottiene con il trigger
  dell'oscilloscopio sul fronte (tensione di uscita, sonda di corrente o uscita di
  trigger del carico), non con la sincronizzazione software.
- All'host resta solo l'**ordine delle operazioni**, che tollera latenze di ms:
  configura carico (dinamico, ancora spento) → configura e arma lo scope →
  attendi "armato" → abilita il carico → attendi l'acquisizione → leggi la forma
  d'onda.
- Per un singolo step (non periodico) il metodo è lo stesso: scope in
  single-shot armato, poi step. Se il carico non ha un modo step/dinamico adatto,
  è un limite dello strumento, da dichiarare nella libreria come capability mancante
  (e il modulo rifiuta la misura con un errore chiaro).

Conclusione: **non serve un esecutore di sequenze nativo**. Il Rust si limita al
trasporto (bassa latenza per query/waveform, thread-safe). Si riconsidera solo se
un modulo futuro richiede davvero azioni software a tempo controllato.

**Regola di sviluppo:** si ottimizza con i numeri. Si aggiunge un benchmark di
latenza e jitter al repo (come quello sopra, più uno strumento simulato) e si porta
in nativo solo ciò che il benchmark mostra come insufficiente.

## 5. Sistema a moduli

### 5.1 Struttura di un modulo

```
mymodule/
  module.json     # manifest: id, nome, versione, api_version, estensione file (UNICA),
                  #           ruoli strumento richiesti, dipendenze Python
  measurement.py  # classe che implementa l'interfaccia Measurement
  schema.json     # schema dei parametri → editor generato automaticamente
  editor.py       # (opzionale) editor Qt custom
```

**Estensioni:** ogni tipo di misura ha la sua (`.eff` efficienza; proposte: `.bode`,
`.rpl` ripple, `.ltr` transitorio, `.tlg` logging, `.spc` spectrum, `.vna`). Il
registro rifiuta due moduli con la stessa estensione; i moduli utente devono
dichiararne una propria.

Posizioni di ricerca:

1. `frontend/measurements/builtin/` – moduli integrati;
2. cartella utente (es. `~/.open_lab_automation/modules/`);
3. `modules/` dentro il progetto (moduli specifici di quel progetto).

### 5.2 Interfaccia `Measurement`

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

### 5.3 Strumento generico, ruoli e capability (il punto chiave)

**Il modulo non conosce SCPI né il modello.** Python (modulo) → API generica →
OpenLab traduce in SCPI dalla libreria → trasporto:

```python
psu = ctx.instrument("psu")        # ruolo → strumento reale del .inst
psu.set_voltage(20.0)              # OpenLab: controlla limiti, traduce, invia
psu.output(True)
v = dmm.measure_voltage()
```

Se il valore supera i limiti dello strumento (es. 20 V su un alimentatore da 15 V)
OpenLab **non invia nulla** e solleva un errore con codice standard
(`[INST-xxx]`, da aggiungere a `ERROR_CODES.md`) che il runner mostra e che manda
la misura in `teardown()`. Il modulo non può aggirare i limiti.

Una misura non dice "usa il Keysight 34972A": dice "mi serve un *generatore
di funzioni*, un *oscilloscopio*". L'utente associa i ruoli agli strumenti del
`.inst`. Gli strumenti dichiarano le **capability** nella libreria (es.
`awg`, `scope`, `dmm`, `psu`, `eload`, `spectrum`, `vna`, `power_meter`), con
i comandi SCPI definiti dalla libreria, come già avviene oggi.
Così lo stesso modulo funziona con strumenti diversi e un nuovo strumento si
aggiunge solo estendendo la libreria.

### 5.4 Sicurezza dei moduli utente

Un modulo utente è codice Python arbitrario che pilota hardware: va
dichiarato esplicitamente (avviso al primo caricamento, elenco in
Impostazioni, possibilità di disabilitarli). Il framework garantisce
`teardown()` anche in caso di errore/stop, e i limiti di sicurezza degli
strumenti (max V/I/P dalla libreria) sono applicati nel livello strumenti,
non lasciati al modulo.

### 5.5 UI

- Dialog "Aggiungi misura" che elenca i tipi disponibili.
- Editor generico generato dallo `schema.json` (campi, range, unità, validazione).
- Pannello **Run** unico per tutti i tipi: avvio/stop/pausa, progresso,
  grafico live, tabella dati, export.

## 6. Misure previste

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
accensione/spegnimento.

## 7. Nuovi strumenti da aggiungere alla libreria

Priorità alta (servono alle misure 2–7):

- **Generatore di funzioni / AWG** – indispensabile per Bode e transitori.
- **Spectrum analyzer** (richiesto).
- **VNA** (richiesto).

Priorità media:

- **Multimetro da banco (DMM)** a sé stante, oltre al datalogger.
- **Power meter / power analyzer** (Yokogawa WT, ecc.): misura di potenza vera
  per un'efficienza più accurata, soprattutto lato AC/forme d'onda distorte.
- **Source-Measure Unit (SMU)**: curve I-V, caratterizzazione.

Priorità bassa / futuro:

- **LCR meter / impedance analyzer** (caratterizzazione di condensatori e induttori).
- **Sorgente AC programmabile**.
- **Frequenzimetro / contatore**.
- **Matrice di relè / multiplexer** (più punti di misura con un solo strumento).

### Categorie da aggiungere alla libreria (✅ elenco approvato)

Oggi: alimentatore, datalogger, oscilloscopio, carico elettronico. Proposta di nuove
categorie, ciascuna con il proprio **insieme di azioni generiche** (i "verbi" che
i moduli useranno, mappati a SCPI nella libreria) e i propri **limiti** dichiarati:

| Categoria | Azioni generiche (esempi) | Limiti dichiarati |
|---|---|---|
| `function_generator` | forma d'onda, frequenza, ampiezza, offset, uscita on/off, carico 50 Ω/HiZ, sweep, burst | Vpp max, f max |
| `spectrum_analyzer` | centro/span, RBW/VBW, reference level, trace, marker, peak search | range f, livello max ingresso |
| `vna` | f start/stop, punti, IFBW, potenza, parametro S, calibrazione, trace complessa | range f, potenza max |
| `multimeter` | funzione (V/I/R…), range, NPLC, trigger, lettura | range per funzione |
| `power_analyzer` | V/I/P/PF, integrazione, range, filtro | V/I max |
| `smu` | forza V/I, compliance, misura V/I, sweep | V/I/P max |

A priorità più bassa, ma da creare comunque come categorie: `lcr_meter`,
`ac_source`, `frequency_counter`, `switch_matrix`.

**Per ora solo categorie, nessuno strumento nella libreria:** le categorie nascono
vuote. Unica eccezione: il **LiteVNA** dell'autore (assunto LiteVNA64), primo
strumento della categoria `vna`.

### 7.1 Conseguenza: il livello strumento non può assumere SCPI

Il LiteVNA è un VNA portatile in stile NanoVNA: si collega via **USB seriale**, non
via LAN, e parla un **protocollo proprio** (shell testuale in stile NanoVNA e/o
protocollo binario), non SCPI. (Da verificare sul manuale/firmware: non lo do per
certo.) Quindi il livello strumento si divide in due parti indipendenti:

| Parte | Esempi |
|---|---|
| **Transport** | TCP/LXI, seriale/USB-CDC, (poi) VISA/GPIB |
| **Protocol** | `scpi` (la maggior parte degli strumenti), `nanovna` (LiteVNA), eventuali altri |

La libreria dichiara per ogni strumento transport + protocol e mappa i **verbi
generici** (es. `vna.set_sweep(f_start, f_stop, points)`, `vna.read_sparam("S21")`)
sul protocollo giusto: stringhe SCPI per gli uni, comandi shell/binari per l'altro.
I moduli restano identici. Impatto sul Rust: il crate dovrà gestire anche la seriale
(prima di quanto previsto) e le letture binarie.
Per le categorie esistenti va fatto lo stesso lavoro: elencare i verbi generici che
oggi sono sparsi in `RemoteControlTab` e in `sweep.c`.

Ogni strumento nuovo richiede: tipo + capability nella libreria, comandi SCPI
nel JSON, dialog di configurazione e (se serve) estensione dell'editor `.inst`.

## 8. Dati

- Modello `Run` generico (rinomina di `SweepSession`), con:
  `run_id`, `measurement_id`, `started_at`, parametri usati (snapshot),
  strumenti usati.
- Tre tipi di dato oltre ai punti scalari: **serie temporali**, **forme
  d'onda/tracce** (scope, spectrum), **dati complessi** (VNA, Bode).
- Salvataggio incrementale durante la run (un crash non perde tutto).
- Export CSV in ogni caso; altri formati (Touchstone, xlsx) per modulo.
- Grandezze derivate come formule tra variabili (es. `eta = Pout/Pin`).

## 9. Fasi di sviluppo

**Fase 0 – Base**
- **Fix immediato del trasporto C**: `TCP_NODELAY` + un solo `send` per comando
  (da ~44 ms a ~30 µs per query), con test.
- Benchmark di latenza/jitter nel repo e strumento simulato (mock) per sviluppare
  e testare senza hardware.
- Test di regressione sull'attuale pipeline dell'efficienza.

**Fase 1 – Core**
- Interfaccia `Transport` (implementazione Python) e strato strumento generico
  (verbi → SCPI dalla libreria, controllo limiti, errori `[INST-xxx]`).
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

**Fase 3b – Livello nativo (Rust)** *(può anticipare: è indipendente dai moduli)*
- Trasporto in Rust (TCP, poi seriale/USB), esposto a Python via PyO3/maturin.
- Nessun esecutore di sequenze nativo (§4.3).

**Fase 4 – Strumenti avanzati**
- Spectrum analyzer, VNA, relative misure (6, 7).
- Bode via VNA.

**Fase 5 – Rifinitura**
- Documentazione per scrivere un modulo (con modulo di esempio).
- Confronto tra run, report, formule derivate.
- Validazione dell'efficienza su hardware reale.

## 10. Punti aperti

- ✅ Rust per lo strato nativo (trasporto).
- ✅ Elenco categorie approvato; solo categorie, nessuno strumento tranne il VNA.
- ✅ Test a impulsi: gestito dal modo dinamico del carico + trigger dello scope (§4.3).
- ✅ `thermal_chamber` tolta dalle categorie.
- ❓ **LiteVNA**: confermare il modello (assunto LiteVNA64) e il protocollo (§7.1).
- ❓ **Verbi generici** per ogni categoria (§7): da definire insieme alla libreria,
  partendo dalle categorie esistenti.
- ❓ **Libreria strumenti**: `Instruments_LIB` è un repo separato (`instruments_lib`):
  le nuove categorie vanno create lì in coordinamento con questo repo.
- ❓ **Moduli utente**: solo Python nella prima versione (proposta); API stabile
  (`api_version`) da congelare prima di documentarla.
- ❓ **Lingue**: ogni modulo porta un proprio `lang/` opzionale (proposta).
