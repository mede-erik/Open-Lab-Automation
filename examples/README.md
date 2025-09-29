# Progetti di Esempio - Open Lab Automation

Questa cartella contiene progetti di esempio per dimostrare le funzionalità del software Open Lab Automation.

## 📁 Contenuto

### `test-dcdc-project/`
Progetto di esempio per test di convertitori DC-DC con visualizzazione delle variabili di misura.

**File inclusi:**
- `Test DC-DC Converter.json` - File progetto principale
- `test_instruments.inst` - Configurazione strumenti di esempio

**Strumenti configurati:**
- **Datalogger Keysight 34972A** - Monitoraggio tensioni e temperatura
- **Multimetro Keysight 34450A** - Misure di precisione corrente
- **Alimentatore Keysight E36312A** - Alimentazione e bias

## 🚀 Come Usare gli Esempi

### 1. Avvia l'Applicazione
```bash
cd /home/mede/Documenti/Github/Open-Lab-Automation
/home/mede/Documenti/Github/Open-Lab-Automation/.venv/bin/python frontend/main.py
```

### 2. Apri il Progetto di Esempio
1. **File** → **Apri Progetto**
2. Naviga in `examples/test-dcdc-project/`
3. Seleziona `Test DC-DC Converter.json`

### 3. Visualizza le Funzionalità
- **Tab "Remote Control"**: Pannello di controllo con visualizzazione misure
- **Riquadro superiore**: Variabili di misura dai datalogger/multimetri
  - Format: `Nome_variabile = valore unità`
  - Aggiornamento automatico configurabile
- **Riquadri inferiori**: Controlli per alimentatori

## ⚙️ Configurazione Strumenti

### Variabili di Misura Configurate
- `Vin_Monitor = --- V` (Tensione ingresso, attenuazione 10:1)
- `Vout_Monitor = --- V` (Tensione uscita)
- `Iin_Monitor = --- A` (Corrente ingresso)
- `Temperature = --- °C` (Temperatura)
- `Iout_Precise = --- A` (Corrente uscita precisa)

### Controlli Alimentatori
- **Vin_Supply**: Alimentazione principale (0-20V, 0-5A)
- **Vbias_Supply**: Alimentazione ausiliaria (0-6V, 0-1A)

## 📝 Note

- Gli indirizzi VISA sono di esempio (`192.168.1.xxx`)
- Senza strumenti reali connessi, le misure mostreranno `NC` (Non Connesso)
- La configurazione può essere modificata tramite il pannello configurazione strumenti
- I canali disabilitati non vengono mostrati nel pannello delle misure

## 🔧 Personalizzazione

Per creare il tuo progetto basato su questo esempio:

1. Copia la cartella `test-dcdc-project`
2. Rinomina i file con il nome del tuo progetto
3. Modifica `test_instruments.inst` con i tuoi strumenti
4. Aggiorna gli indirizzi VISA con quelli reali
5. Configura canali, unità di misura e attenuazioni

## 📚 Documentazione Aggiuntiva

- Vedi `frontend/TODO.md` per specifiche implementazione
- Controlla `Instruments_LIB/` per strumenti supportati
- Leggi i commenti nel codice per dettagli tecnici