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

> **Implementato** in `ola/project.py` (descrizione: `docs/engine.md`). Differenze rispetto
> a questo schema iniziale: il file di progetto ha anche `"format_version": 2`; il vecchio
> formato (`eff_files`/`was_files`) viene rifiutato con un errore chiaro; i nomi dei file
> devono essere nomi semplici (niente percorsi, `..` rifiutato).

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
| Strumento generico + limiti; traduttore SCPI **o** driver (§7.1) | Python (prima versione) | Guidato dalla libreria, facile da estendere |
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

> **Implementato** in `ola/measurement.py`, `ola/runner.py`, `ola/registry.py`; guida per chi
> scrive un modulo: `docs/measurement-modules.md`. Differenze rispetto al design iniziale
> qui sotto: `validate(self)` non riceve argomenti (usa `self.params`); i ruoli sono oggetti
> `Role(name, category, required, multiple)` letti dal `module.json`, non una mappa di
> `Capability`; l'arresto si controlla con `ctx.checkpoint()` / `ctx.sleep()` (non
> `should_stop()` / `pause_point()`); il manifest ha `entry` (`file.py:Classe`); la cartella dei
> moduli integrati è `ola/modules/` (non `frontend/measurements/builtin/`); `schema.json` e
> `editor.py` non esistono ancora (`params_schema` sta nel manifest e non è applicato).

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
OpenLab traduce in SCPI dalla libreria **oppure passa la chiamata a un driver**
(§7.1) → trasporto:

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
i comandi SCPI definiti dalla libreria (come oggi) oppure, per gli strumenti
proprietari, con un driver (§7.1).
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

Oggi la libreria ha: `power_supplies`, `dataloggers` (+ `datalogger_modules`), `switch_units`,
`multimeters`, `oscilloscopes`, `electronic_loads` (chiavi `*_series`). Proposta di nuove
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
`ac_source`, `frequency_counter`. (`multimeter` e `switch_matrix` esistono già nella
libreria come `multimeters_series` e `switch_units_series`.)

**Per ora solo categorie, nessuno strumento nella libreria:** le categorie nascono
vuote. Eccezioni, come banco di prova (§7.1): il **LiteVNA67** (categoria `vna`) e,
in seguito, l'**Analog Discovery 2** (dispositivo composito).

### 7.1 Strumenti non SCPI: LiteVNA67 (comandi su seriale) e Analog Discovery 2/3 (driver)

Molti strumenti da hobbista non sono SCPI. Sono un target primario del progetto e
si dividono in due casi diversi:

1. **LiteVNA67** (stesso protocollo del LiteVNA64): si comanda con **stringhe su
   seriale**. È compatibile con la struttura attuale della libreria (come il
   datalogger HP con interfaccia seriale): per ogni azione la libreria contiene la
   stringa da inviare. Non serve un driver.
2. **Analog Discovery 2 e 3** (Digilent): si pilotano solo con l'**SDK WaveForms**
   (runtime installato sul PC), non con comandi testuali. Per questi serve un
   **driver**. Stessa famiglia di driver per AD2 e AD3.

> Da verificare sul campo: protocollo reale del LiteVNA67 (testuale e/o binario;
> l'autore invierà VID/PID e informazioni) e funzioni dell'SDK WaveForms.

#### Due modalità di accesso

(Vocabolario concordato con la sessione libreria/planner: `access` = `scpi` | `driver`. `scpi` significa "piano a passi di testo eseguito dall'esecutore generico" e vale anche per protocolli testuali non-SCPI come il LiteVNA.)

| `access` | Chi sa parlare con lo strumento | Cosa descrive la libreria | Esempi |
|---|---|---|---|
| `scpi` | Traduttore generico di OpenLab | Tabella verbo → stringa da inviare (SCPI o no), trasporto (LAN, seriale, …), come interpretare le risposte, limiti | Strumenti SCPI, datalogger HP seriale, **LiteVNA67** |
| `driver` | **Un driver** (codice, uno per famiglia) | Identità, capability, limiti, rilevamento, **nome del driver** | **Analog Discovery 2/3** (famiglia WaveForms) |

Il punto chiave: **in entrambi i casi il modulo di misura vede la stessa interfaccia**.
Il traduttore a comandi e i driver implementano gli stessi contratti per categoria
(`PowerSupply`, `Scope`, `FunctionGenerator`, `Vna`, …):

```python
class Vna(Protocol):                       # contratto della categoria "vna"
    def set_sweep(self, f_start, f_stop, points, ifbw=None, power_dbm=None): ...
    def read_sparam(self, name: str) -> ComplexTrace: ...   # "S11", "S21", ...
```

Il traduttore a comandi genera stringhe (SCPI per un oscilloscopio, comandi del
LiteVNA per il VNA); il driver dell'AD2 chiama l'SDK. Il modulo scrive
`vna.read_sparam("S21")` e basta.

#### Dove vive cosa

- **Libreria (JSON, solo dati, nessun codice):** identità, categorie/capability,
  limiti dichiarati, regole di rilevamento (VID/PID USB, nome porta) e, per `driver`,
  l'**id del driver**. Per `scpi`: le stringhe e le regole di interpretazione delle risposte. Un repo di dati non deve poter eseguire codice sul PC
  dell'utente.
- **Driver (codice Python), solo per gli strumenti che li richiedono:** in questo repo (`frontend/drivers/`, integrati) o in
  una cartella utente. Usano lo **stesso meccanismo dei moduli di misura**
  (manifest, `api_version`, registro, avviso per codice di terzi): il sistema ha due
  tipi di modulo, *measurement* e *driver*.
- Se la libreria cita un driver non installato, lo strumento compare come **non
  supportato** con un messaggio chiaro, non come errore a runtime.

Esempio di voce `scpi` (LiteVNA67 su seriale, schema indicativo):

```json
{
  "id": "litevna_67", "name": "LiteVNA67", "access": "scpi",
  "connection": {"transport": "serial", "usb": {"vid": "TODO", "pid": "TODO"},
                 "baud": "TODO", "terminator": "TODO"},
  "capabilities": {
    "vna": {"f_min_hz": "TODO", "f_max_hz": "TODO", "points_max": "TODO"}
  },
  "commands": {
    "vna.set_sweep": "TODO  (comando con segnaposto {f_start} {f_stop} {points})",
    "vna.read_sparam": {"send": "TODO", "parse": "complex_lines"}
  }
}
```

Esempio di voce `driver` (Analog Discovery, schema indicativo):

```json
{
  "id": "analog_discovery_2", "name": "Analog Discovery 2", "access": "driver",
  "driver": "digilent_waveforms",
  "requires": ["WaveForms runtime"],
  "capabilities": {
    "scope": {"channels": 2, "...": "da datasheet"},
    "function_generator": {"channels": 2, "...": "da datasheet"}
  }
}
```

Limite del modello `scpi`: se le risposte del LiteVNA sono **binarie** o richiedono
un parsing non descrivibile con le regole standard (float, lista di float, righe di
numeri complessi, blocco binario con header), serve un'estensione del formato di
risposta, o in ultima istanza un piccolo driver. Si decide quando si vedono le risposte
reali del dispositivo.

I valori reali (VID/PID, range, punti) vanno presi dal dispositivo e dal manuale;
qui sono segnaposto.

#### Strumenti compositi: un dispositivo, più strumenti logici

L'AD2 è oscilloscopio a 2 canali, generatore di forme d'onda a 2 canali,
alimentazioni ±, voltmetro, I/O digitali, analizzatore logico, analizzatore di
impedenza… in **un solo dispositivo USB**. La libreria oggi ha "un tipo per modello":
va esteso a **più capability per modello**. Nel `.inst` il dispositivo si inserisce
una volta e **espone strumenti logici** (`ad2.scope`, `ad2.awg`, `ad2.psu`, …) a cui si
associano i ruoli delle misure. Ne seguono due regole:

- **Sessione condivisa:** il dispositivo si apre una volta sola e tutti gli strumenti
  logici la condividono, con un lock (un dispositivo = un handle, una sola misura
  alla volta lo usa).
- **Sincronizzazione hardware:** l'AD2 può avviare scope e generatore insieme
  (trigger incrociati). Le capability espongono opzioni come
  `scope.trigger_source = "awg"`, usate da moduli come Bode e transitorio; per
  strumenti separati si usa il trigger esterno. Questo risolve in hardware il
  problema di timing dei test a impulsi (§4.3).

#### Cosa resta uguale (e viene garantito sopra il driver)

- **Limiti:** il controllo (es. tensione > massimo dichiarato) sta nello **strato
  strumento generico, sopra** i driver. Un driver non può saltarlo, quindi la
  sicurezza è identica per SCPI e per driver.
- **Errori:** i driver sollevano gli errori standard `[INST-xxx]`; dipendenza
  mancante (es. WaveForms non installato, porta seriale occupata) = errore
  esplicito con istruzioni.
- **Rilevamento automatico:** per i dispositivi USB l'`Add instrument` può elencare
  quelli collegati (VID/PID, WaveForms `enumerate`) invece di far scrivere un indirizzo.
- **Simulazione:** ogni contratto ha un'implementazione simulata per sviluppare e
  testare senza hardware (già prevista in Fase 0).

#### Impatto sul Rust

- Il trasporto Rust serve tutti gli strumenti `scpi` (seriale del LiteVNA,
  TCP/LXI, seriale del datalogger HP): seriale e letture binarie sono nel perimetro
  dall'inizio.
- I driver **che usano un SDK di terzi** (AD2/AD3, WaveForms) lo chiamano
  direttamente (ctypes/binding Python) e non passano dal trasporto Rust: non c'è un
  flusso di byte da gestire.

#### Banco di prova

Il piano usa i due strumenti reali dell'autore come validazione dell'architettura:

1. **LiteVNA67** → primo strumento `vna` in modalità `scpi` su seriale (valida
   il formato delle risposte e il trasporto seriale).
2. **Analog Discovery 2** (poi 3) → primo `driver`: strumento composito: `scope` + `function_generator`
   (+ `psu`/voltmetro) → permette di provare **Bode**, **ripple** e **transitorio**
   senza altro hardware.

### 7.2 La libreria esistente definisce già i "verbi" (branch `claude/charming-bell-768j4j`)

Lettura del lavoro in corso su `instruments_lib` (un altro agente + l'autore; **non
modifico quel repo finché il lavoro non è unito**). Cosa implica per questo piano:

- **I verbi generici sono i nomi di chiamata della libreria** (`COMMAND_NAMES.md`):
  `set_voltage`, `read_voltage`, `output_on`, `set_mode`, `set_trigger_level`,
  `query_waveform_data`… con chiamate *obbligatorie* e *opzionali* per categoria.
  Non serve inventare un secondo vocabolario: i contratti Python delle categorie
  (`PowerSupply`, `Scope`, …) sono uno strato sottile sopra questi nomi, e per i
  `driver` (AD2/AD3) dovranno implementare gli stessi nomi.
- **Regola della libreria, da rispettare nel codice:** il software non costruisce mai
  stringhe SCPI; una chiamata assente significa "non supportata da questo strumento",
  mai sostituita con una stringa ipotizzata. Si traduce in un errore esplicito
  `[INST-xxx]` ("chiamata non supportata"), non in un tentativo.
- **Struttura di una chiamata:** `set` / `query` con `syntax` (segnaposto `{nome}`),
  `args`, `return_type` (`string|int|float|binary`) e `parameters` (`type`, `values`).
  `return_type: binary` corrisponde a `read_block()` del trasporto.
- **Override per modello** (`replace` / `null` = rimossa / `{"patch": …}` deep-merge):
  la risoluzione è in `LoadInstruments.resolve_model_commands()`. Lo strato strumento
  deve usare quella risoluzione, non duplicarla. Oggi sta in `frontend/core`, che
  importa PyQt6: va estratta in un modulo senza Qt (es. `ola/library.py`) con
  `LoadInstruments` come wrapper sottile.
- **Limiti** letti da `capabilities` (es. `voltage_output.min/max` per canale, per gli
  alimentatori; `max_voltage_v`, `max_current_a`, `max_power_w` per i carichi): base
  del controllo "20 V su un alimentatore da 15 V".
- **Chiamate con più comandi** (in corso nell'altro branch: alcuni strumenti ne
  richiedono due per una stessa azione): l'esecutore deve trattare una chiamata come
  una **sequenza di passi**, non come una stringa. Punti da definire con l'altro
  agente: (a) schema esatto (lista di passi? passi con `query`?); (b) i passi vanno
  inviati **in modo atomico** (es. `INST:NSEL 2` poi `VOLT 5`: un altro thread non
  deve poter cambiare canale nel mezzo → lock per strumento nello strato generico,
  non solo per singola query); (c) se la libreria può indicare che i passi si
  possono unire in un solo messaggio (separatore `;`) per ridurre la latenza, o se
  vanno sempre inviati separatamente (default sicuro: separati).
  Nota: `backend/sweep.c` oggi fa già questo a mano (`INST:NSEL` + `VOLT`).
- **Tipi di connessione** della libreria: `LXI`, `USB-TMC`, `SERIAL`, `GPIB`, con
  indirizzi in stile VISA. Il trasporto Rust copre oggi **TCP raw (porta 5025) e
  seriale**. Lacune da chiudere: **USB-TMC** e **GPIB** (via `pyvisa` come
  implementazione alternativa di `Transport`, o `rusb` per USB-TMC), e il fatto che
  `TCPIP0::ip::inst0::INSTR` è **VXI-11**, non socket raw: non tutti gli strumenti
  LXI accettano il socket 5025 (alcuni solo VXI-11/HiSLIP). La libreria dovrebbe
  indicare quale modalità/porta usare per ogni modello.

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

**Fase 0 – Base** *(fatta, tranne la regressione sull'efficienza)*
- **Fix immediato del trasporto C** *(sostituito dal nuovo trasporto; il C non è stato toccato)*: `TCP_NODELAY` + un solo `send` per comando
  (da ~44 ms a ~30 µs per query), con test.
- Benchmark di latenza/jitter nel repo e strumento simulato (mock) per sviluppare
  e testare senza hardware.
- Test di regressione sull'attuale pipeline dell'efficienza *(non fatto: l'efficienza verrà riscritta)*.

**Fase 1 – Core** *(fatta, per la parte in `ola/`)*
- Interfaccia `Transport` (implementazione Python) e strato strumento generico
  (verbi → SCPI dalla libreria, controllo limiti, errori `[INST-xxx]`).
- Nuovo formato progetto (`measurements[]`), nuovo `ProjectDatabaseManager`.
- Interfaccia `Measurement`, `Capability`, contesto di esecuzione, runner in thread.
- Modello `Run` generico.

**Fase 2 – Moduli** *(registro fatto; editor generico, efficienza e pannello Run da fare)*
- Registro/loader dei moduli (integrati + utente + progetto) con manifest.
- Editor generico da `schema.json`.
- Efficienza riscritta come primo modulo integrato.
- Pannello Run unico (live, stop/pausa, export).

**Fase 3 – Prime nuove misure** *(solo il logging nel tempo è fatto)*
- Logging nel tempo (la più semplice: valida il runner e i dati temporali).
- Ripple e rumore.
- Strumento AWG nella libreria → Bode (con scope).
- Transitorio di carico.

**Fase 3b – Livello nativo (Rust)** *(fatta: TCP e seriale; USB-TMC/GPIB passano da pyvisa)*
- Trasporto in Rust (TCP, poi seriale/USB), esposto a Python via PyO3/maturin.
- Nessun esecutore di sequenze nativo (§4.3).

**Fase 4 – Strumenti avanzati**
- Spectrum analyzer, VNA, relative misure (6, 7).
- Bode via VNA.

**Fase 5 – Rifinitura**
- Documentazione per scrivere un modulo (con modulo di esempio) *(fatta: `docs/measurement-modules.md`, esempio verificato da un test)*.
- Confronto tra run, report, formule derivate.
- Validazione dell'efficienza su hardware reale.

## 9b. Stato di avanzamento

- ✅ **Trasporto Rust** (`native/`): TCP (`TCP_NODELAY`), seriale, blocchi IEEE 488.2,
  timeout con deadline, GIL rilasciato, errori `TRN-xxx`. 13 test Rust; documentazione `///` completa
  (`#![warn(missing_docs)]`, nessun avviso).
- ✅ **Livello Python** (`ola/`): `ola.transport` usa il modulo nativo o, se assente,
  un'implementazione Python equivalente (stessa suite di test su entrambe).
- ✅ **Benchmark** (`benchmarks/bench_transport.py`), mediana su loopback: backend C
  attuale 44 ms; Python 55 µs; Rust 34 µs (p99 101 µs); trasferimento di 1 MB: Python
  552 MB/s, Rust 2124 MB/s.
- ✅ **Esecutore dei passi** (`ola/instrument.py`, `ola/steps.py`): una chiamata è una
  lista di passi `write`/`query`/`delay` (+ `timeout_ms`, `returns` float|int|string|binary)
  eseguita sotto **un lock per strumento** per tutta la chiamata; stop al primo errore
  → `CALL-004` con indice del passo; dopo un errore l'input pendente viene scartato;
  annullamento (`cancel`) anche durante un `delay`; dispatcher per i piani `driver`
  (AD2/AD3). Le mappe e l'interpretazione delle risposte restano nel planner
  (altra sessione). Strumento simulato: `ola/sim.py`.
- ✅ **Adattatore pyvisa** (`ola/_visa.py`): stessa interfaccia del trasporto, per
  USB-TMC, GPIB e VXI-11. Testato con `pyvisa-py` su socket; **non** testato con una
  libreria VISA reale né su hardware.
- ✅ **Accordo con la sessione "libreria/planner"** (branch `claude/charming-bell-768j4j`):
  planner e risoluzione della libreria vivono in `ola/` (senza Qt); un solo trasporto;
  formato dei passi e del piano concordati; item 14 (export del piano) rimandato.
  L'ordine di merge dei due branch lo decide l'autore.
- ✅ **Nucleo delle misure** (Fase 1, solo file nuovi in `ola/`, senza Qt):
  `measurement.py` (classe `Measurement`, `MeasurementContext`, ruoli, eventi),
  `runner.py` (thread: setup → run → teardown **sempre**; stop, pausa, errori con codice e
  traceback; derivate; listener), `registry.py` (moduli da `module.json`: la scoperta **non
  esegue codice**, il codice dei moduli non integrati si carica solo con permesso esplicito;
  id ed estensione file unici), `project.py` (progetto con `measurements[]`, un file per
  misura, nomi file sicuri), `runs.py` (risultati scritti durante la run, JSON Lines,
  leggibili anche dopo un crash; export CSV), primo modulo `ola/modules/time_log`
  (`.tlg`, campionamento senza deriva). Interfaccia verso gli strumenti: `handle.call(nome,
  **argomenti)`, da collegare a libreria + planner + esecutore (lavoro dell'altra sessione).
- 📌 **Decisioni dell'utente (2026-11-03):** nessuna retrocompatibilità con il vecchio
  `.eff` (verrà riscritto e ripensato: nessun lettore né convertitore) e con il vecchio
  formato di progetto; il pulsante "Avvia misura" nella GUI si farà quando saranno
  definiti i tipi di misura.
- 📌 **`backend/` (C): non estendere, da ritirare.** `backend/sweep.c` usa SCPI fissi
  (`INST:NSEL`, `VOLT`, `MEAS:VOLT?`...) contro la regola "solo comandi della libreria", e
  `frontend/core/c_backend.py` non è chiamato dalla GUI. Si ritira insieme a `c_backend.py`
  dopo il collegamento di `ola.transport` all'app.
- ✅ **Documentazione** (2026-11-03): sezione "Engine" nel `README.md`; guide in `docs/`
  (`engine.md`, `measurement-modules.md`, `instrument-calls.md`); docstring su tutti gli
  elementi pubblici di `ola/`; contratto `Transport` (`ola/transport.py`) verificato su
  tutte le implementazioni. **Documentazione tenuta allineata da test**
  (`tests/test_docs.py`, `tests/test_transport_contract.py`): falliscono se manca una docstring,
  se un file di `ola/` non è nel README, se un codice `TRN-xxx` non è in `ERROR_CODES.md`, se
  un link relativo è rotto o se l'esempio di `docs/measurement-modules.md` non funziona.
  Totale: 201 test Python (con trasporto nativo e con `OLA_TRANSPORT=python`).
- ✅ **Misura di efficienza** (`.eff` nuovo; `ola/modules/efficiency/`, `ola/efficiency_spec.py`,
  `ola/formula.py`, `ola/sweep.py`; guida `docs/efficiency.md`). Decisioni dell'utente (2026-11-03):
  parametri con nomi scelti dall'utente, ciascuno con *impostazione* e/o *letture* (anche più
  letture dello stesso parametro, per esempio dall'alimentatore e dal datalogger); nelle formule
  `vin` è il valore impostato e `vin@daq` la lettura con quell'etichetta (la scelta della lettura
  è esplicita); **elenco ordinato** di parametri riordinabile: il primo cambia per primo ed è
  lo sweep più interno; per ogni punto: attesa, N letture a intervallo scelto, **media delle
  letture** e formule sulle medie; se la lettura indipendente si discosta dall'impostazione oltre la
  tolleranza la misura **si ferma e chiede** (Riprova / Annulla / Salta); la validazione avviene
  **mentre si compila il dialog** (`validate_params`, errori con il percorso del campo).
  Nel nucleo: più tabelle di righe (`points`, `samples`), `ctx.ask` / `runner.answer`, stato
  `waiting`. Provata solo su strumenti simulati.
  **Uscite, cooldown e ordine di accensione** (2026-11-03): ogni parametro impostato può avere un
  blocco `output` (chiamate `on`, `off` e, facoltativa, `state`; e `mode`): `keep_on` (predefinito),
  `off_during_cooldown` e `always_on` ("sempre attivo"). Il **cooldown** (`timing.cooldown_s`) è un
  riposo del convertitore **tra uno sweep e l'altro, non tra i punti**: quando lo sweep più interno ha
  finito il suo giro e un parametro esterno avanza, le uscite `off_during_cooldown` si spengono, si
  attende, poi i parametri vengono reimpostati e le uscite riaccese; non c'è cooldown dopo l'ultimo
  sweep. L'**ordine di accensione** è una lista a parte (`power_order`, riordinabile; spegnimento in
  ordine inverso; predefinito = ordine dei parametri) che **esclude** le uscite sempre attive: queste si
  accendono prima di tutto il resto. Se l'uscita ha una chiamata `state` il programma chiede se è già
  accesa: se lo è la lascia com'è, se è spenta la accende; un'uscita sempre attiva non viene **mai**
  spenta (né nel cooldown né alla fine, dopo un errore, uno stop o un annullamento). Un `shutdown`
  che la spegne è un errore di validazione. Un'uscita gestita dal programma (da spegnere a fine misura) che
  è già accesa all'avvio viene comunque spenta a fine misura (decisione dell'utente), ma **prima di toccare
  qualsiasi strumento** compare un pop-up che la elenca e chiede Continua / Annulla (per modificare il
  file); Annulla termina la misura come "fermata" senza cambiare né spegnere nulla. Serve la chiamata
  `state`; senza, la validazione avvisa che il controllo non è possibile.
  **GUI, editor dell'efficienza** (2026-11-03): modello senza Qt `ola/efficiency_editor.py` (29 test) +
  finestra PyQt6 sottile `frontend/ui/EfficiencyEditorDialog.py` (test offscreen con pytest-qt). Ogni
  campo è legato a un percorso dei parametri; errori in rosso/avvisi in ambra sul campo, elenco dei
  problemi con doppio clic per andare al campo, riga di riepilogo (punti, sweep, raffreddamenti, tempo).
  Schede: Parametri (lista ordinabile con Su/Giù), Tempi, Formule, Ordine di accensione (+ chiamate
  extra), Anteprima del file. Stringhe in `frontend/lang/modules/efficiency/{en,it,fr,es,de}.json`
  (test: stesse chiavi in tutte le lingue). Salvataggio con errori solo dopo conferma.
  **GUI, finestra di esecuzione** (2026-11-03): modello senza Qt `ola/run_view.py` (`RunModel`: stato,
  avanzamento e tempo residuo senza contare le attese dell'utente, tabella, log, domande aperte, serie
  per i grafici) + finestra sottile `frontend/ui/RunWindow.py` (Avvia/Pausa/Riprendi/Ferma, tabella dal
  vivo, grafico QPainter senza librerie esterne con una linea per ogni valore di un parametro, log,
  esportazione CSV) e **pop-up per le domande della misura** (un pulsante per scelta, quella sicura è
  predefinita e in grassetto, non si chiude senza risposta, si chiude da sola se la misura viene fermata).
  Stringhe in `frontend/lang/modules/run/{en,it,fr,es,de}.json`. Demo con strumenti simulati
  (`ola/demo_lab.py`): `python -m frontend.ui.RunWindow [--fault]`.
  **GUI, collegamento con il progetto** (2026-11-03): `ola/project_session.py` (`ProjectSession`, senza
  Qt, testata) + `frontend/ui/ProjectWindow.py`: elenco delle misure del progetto (formato 2) con il
  motivo se una non è utilizzabile, Nuova (tipo scelto tra i moduli), Modifica (editor dell'efficienza
  per `.eff`, editor JSON validato per gli altri tipi), **Avvia misura** (apre la finestra di
  esecuzione; risultati in `runs/` nella cartella del progetto), Rinomina, Rimuovi (file tenuto o
  eliminato su richiesta), elenco delle esecuzioni con esportazione CSV. Gli strumenti arrivano
  dall'applicazione tramite `connect(nome) -> handle`; senza, "Avvia" spiega che non sono collegati.
  **Integrazione in `main_window.py`** (2026-11-03): il segnaposto "Avvia Efficienza - in arrivo" è
  sostituito dalla scheda **Misure** (`ProjectWindow`, 6 righe; non tocca le parti modificate dal ramo
  `wonderful-mccarthy`, i due rami si uniscono senza conflitti). Il flusso vecchio (`eff_files`, lista a
  sinistra) resta com'è. `connect` è `not_connected` (messaggio chiaro, non parte nulla): **va sostituito
  con la funzione che restituisce l'`InstrumentHandle` dal `.inst`** quando il ramo `charming-bell`
  (libreria, planner, handle) sarà unito. Nota: `charming-bell` e `wonderful-mccarthy` in conflitto
  tra loro su `.github/workflows/ci.yml` e `scripts/check_translations.py`.
- ⏳ Non ancora fatto: collegare `ola.transport` all'app (il backend C e `c_backend.py` sono
  ancora nel repo e non sono stati toccati), collegare la finestra del progetto a `main_window` e agli strumenti reali (`connect`, dal ramo di libreria/handle),
  modulo e campi per la seriale testuale del LiteVNA67 (`until`/`lines`/`size`/`flush`, in
  attesa dei dati del dispositivo), sistema driver per AD2/AD3, pipeline wheel e CI.

## 10. Punti aperti

- ✅ Rust per lo strato nativo (trasporto).
- ✅ Elenco categorie approvato; solo categorie, nessuno strumento tranne il VNA.
- ✅ Test a impulsi: gestito dal modo dinamico del carico + trigger dello scope (§4.3).
- ✅ `thermal_chamber` tolta dalle categorie.
- ✅ LiteVNA67: modalità `scpi` su seriale, come gli strumenti attuali (§7.1).
- ✅ AD2/AD3: categoria `driver` con runtime WaveForms obbligatorio.
- ❓ **Progetto del sistema driver** (interfaccia, ciclo di vita della sessione,
  rilevamento, installazione del runtime): da discutere.
- ❓ **Dove vivono i driver**: proposta = codice nel repo OpenLab / cartella utente,
  libreria JSON solo dati. Da confermare.
- ❓ **LiteVNA67**: l'autore invierà VID/PID, protocollo e specifiche (in arrivo).
- ❓ **Modello dei dispositivi compositi** nel `.inst` e nella libreria (§7.1).
- ✅ Verbi generici = nomi di chiamata della libreria (§7.2); restano da definire
  solo quelli delle categorie nuove, nel repo della libreria.
- ✅ **Chiamate a più comandi** (§7.2): passi `write`/`query`/`read`/`delay` sotto un lock per
  strumento; l'unione con `;` resta fuori dalla v1.
- ✅ **Connessioni**: USB-TMC/GPIB/VXI-11 via pyvisa (`ola/_visa.py`, provato solo con `pyvisa-py`);
  la modalità per ogni modello (socket raw / VXI-11 / seriale) la dichiara la libreria nel blocco
  `interface` (lavoro dell'altra sessione). Aperto: `rusb` per USB-TMC nativo (non necessario ora).
- ✅ **Estrazione** di `resolve_model_commands()` in un modulo senza Qt: fatta nel branch dell'altra
  sessione (`ola/library.py`), non ancora in `main`.
- ❓ **Libreria strumenti**: `Instruments_LIB` è un repo separato (`instruments_lib`):
  le nuove categorie vanno create lì in coordinamento con questo repo.
- ✅ **Moduli utente**: solo Python; caricare un modulo non integrato richiede un permesso esplicito
  (`allow_user_code`), scoprirlo no. Documentato in `docs/measurement-modules.md`.
- ❓ **Congelare `api_version` 1** (interfaccia `Measurement` / `ctx`): da fare prima di promettere
  compatibilità ai moduli scritti da altri.
- ❓ **Lingue**: ogni modulo porta un proprio `lang/` opzionale (proposta).
