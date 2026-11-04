# Immagini degli schemi di collegamento: cosa disegnare

Elenco delle immagini che i moduli cercano. Sono **13**. Ogni immagine è facoltativa: finché manca, la finestra dei
collegamenti mostra lo schema disegnato dal programma; appena metti il file con il nome giusto, compare il tuo disegno.
Puoi farle una alla volta, in qualsiasi ordine.

Come funziona è spiegato in [`wiring.md`](wiring.md). Qui c'è solo la lista di lavoro.

## Dove mettere i file e come si chiamano

* **Cartella**: quella del modulo, accanto a `wiring.json` (`ola/modules/<modulo>/`). Ogni immagine qui sotto dice la
  sua cartella.
* **Nome**: esattamente quello indicato, in minuscolo, **senza spazi**. L'estensione può essere `.svg` (consigliato),
  `.png`, `.jpg` o `.webp`. Esempio: `ola/modules/filter/filter.svg`.
* **Lingue**: se nel disegno **non ci sono parole**, basta un file. Se ci sono parole, fai un file per lingua con il
  suffisso dopo il nome: `filter_it.svg`, `filter_en.svg`, `filter_fr.svg`, `filter_es.svg`, `filter_de.svg`. Il
  programma usa il file della lingua dell'app e, se manca, quello inglese (`_en`). Se fai solo i disegni con le parole
  in una lingua, chiamali con il suffisso giusto e il resto resta con il disegno del programma.
  **Consiglio**: disegni senza parole (solo simboli, colori e frecce), perché la lista numerata sotto l'immagine dice già
  le cose a parole e nella lingua giusta. Al massimo etichette cortissime e uguali in tutte le lingue (`P1`, `P2`,
  `CH1`, `+`, `-`, `GND`).

## Regole comuni (valgono per tutte)

| Cosa | Indicazione |
|---|---|
| Formato | **SVG** (resta nitido a qualsiasi dimensione). Se PNG: almeno **1500 px di larghezza** |
| Proporzioni | **Orizzontale**, circa 2:1 o 16:9 (per esempio 1600 x 800). Non più alto che largo |
| Sfondo | Bianco oppure trasparente. La finestra la mostra su bianco anche con il tema scuro |
| Margini | Un po' di bianco attorno (circa 5 %): niente cose attaccate al bordo |
| Stile | Sempre lo stesso in tutte le immagini: stessi simboli per gli strumenti, stesso modo di disegnare i connettori |
| Spessore | Linee abbastanza spesse da leggersi quando la finestra è stretta (immagina l'immagine larga 600 px) |
| Colori | Pochi. Proposta: **nero** = segnale / cavo coassiale, **rosso** = positivo / alimentazione, **blu** = negativo / massa, **verde** = il dispositivo in prova (DUT) evidenziato. Se usi colori, non basarti solo su quelli: il DUT va anche **disegnato diverso** (cornice doppia o tratteggiata) |
| Strumenti | Disegnali come li riconosci: il VNA come uno strumento con le porte sul lato, l'oscilloscopio con lo schermo, ecc. Un riquadro con un'icona va bene |
| Connettori | Le **porte numerate** dei VNA (P1, P2) e i **canali** dell'oscilloscopio (CH1) visibili, con il numero |
| DUT | Sempre ben distinguibile dagli strumenti (colore, cornice doppia o ombra) |
| Cavi | Il cavo di test è un tratto spesso con i connettori alle estremità. Se è un cavo che si misura, disegnalo diverso (più lungo, a onda) per non confonderlo con i cavi di test |

Ogni immagine deve far capire **a colpo d'occhio** da dove a dove va ogni filo, senza leggere la lista.

## Prima di cominciare: come provarla

Dopo aver messo il file nella cartella del modulo, per vederla senza avviare nessuna misura:

```bash
python -m frontend.ui.WiringDialog filter
```

(al posto di `filter` il nome del modulo). Per la misura con parametri diversi (es. l'amplificatore **con** attenuatore),
dai anche un file di misura e la lingua: `python -m frontend.ui.WiringDialog amplifier la_mia_misura.amp it`.

---

# Le 13 immagini

Ogni scheda dice: **file**, **cartella**, **quando viene mostrata**, **cosa disegnare** e i **dettagli che devono
esserci**.

## 1. Cavo, trasmissione

* **File**: `cable_transmission`
* **Cartella**: `ola/modules/cable/`
* **Quando si vede**: misura del cavo in trasmissione (il caso normale, perdita tra le due porte).
* **Cosa disegnare**: il **VNA** a sinistra con **P1 e P2** sul lato destro (o ai lati). Il **cavo in prova** al centro,
  disegnato ben visibile e **ripiegato o ondulato** per far capire che è lui il dispositivo in prova (DUT).
  Un'estremità del cavo va a **P1**, l'altra a **P2**, ognuna con un **cavetto di test corto** (i cavetti di test sono
  quelli usati per la calibrazione).
* **Dettagli**: i due cavetti di test **uguali** e corti; le due estremità del cavo etichettate **A** e **B** (A su P1,
  B su P2); un piccolo segno che indichi i **piani di calibrazione** (le due estremità dei cavetti di test, dove si
  attacca il cavo in prova).

## 2. Cavo, riflessione con estremo aperto

* **File**: `cable_reflection_open`
* **Cartella**: `ola/modules/cable/`
* **Quando si vede**: misura in riflessione, con il capo lontano **aperto** (il caso predefinito della riflessione).
* **Cosa disegnare**: il VNA con la sola **P1** collegata. Il cavo in prova parte da P1 (tramite il cavetto di test) e
  **finisce nel vuoto**: il connettore all'altra estremità è **lasciato libero**, con un **simbolo di circuito aperto**
  (tratto interrotto) o la sigla **OPEN**.
* **Dettagli**: **P2 vuota** (non collegata, magari con un tappino o semplicemente senza filo); il capo lontano ben
  visibile, perché è lì che l'utente deve fare attenzione a non collegare niente.

## 3. Cavo, riflessione con estremo in corto

* **File**: `cable_reflection_short`
* **Cartella**: `ola/modules/cable/`
* **Quando si vede**: misura in riflessione con il capo lontano in **cortocircuito**.
* **Cosa disegnare**: come l'immagine 2, ma il connettore lontano ha un **cortocircuito** (un tappo short, oppure il
  simbolo del corto: i due contatti uniti), con la sigla **SHORT**.
* **Dettagli**: **fai le immagini 2 e 3 con la stessa impostazione**, così si vede che cambia solo il capo lontano.

## 4. Return loss

* **File**: `return_loss`
* **Cartella**: `ola/modules/return_loss/`
* **Quando si vede**: misura di return loss / VSWR di un dispositivo (un ingresso, un adattatore, un connettore).
* **Cosa disegnare**: il VNA con **P1** collegata, tramite un **cavetto di test**, al **connettore del dispositivo in
  prova**. Il dispositivo è un riquadro generico (il DUT) con un solo connettore.
* **Dettagli**: **P2 non usata**; indica il **piano di calibrazione** (la fine del cavetto di test) con un tratto
  verticale tratteggiato o un segno, perché la calibrazione si fa lì (open / short / load).

## 5. Antenna

* **File**: `antenna`
* **Cartella**: `ola/modules/antenna/`
* **Quando si vede**: misura dell'impedenza e del return loss di un'antenna.
* **Cosa disegnare**: il VNA con **P1** collegata, con un cavetto di test, al **connettore dell'antenna** (disegna
  un'antenna riconoscibile: stilo, patch o pannello).
* **Dettagli**: l'antenna **lontana da oggetti metallici e da persone**: puoi disegnare un'area libera intorno
  all'antenna, con un piccolo **segno di divieto sul metallo** o semplicemente con spazio vuoto e una freccia che indica
  la distanza. L'antenna deve stare nella **posizione di uso** (se va montata su un tetto, nell'immagine è su un
  supporto, non appoggiata sul tavolo).

## 6. Filtro

* **File**: `filter`
* **Cartella**: `ola/modules/filter/`
* **Quando si vede**: misura della risposta di un filtro (passa-basso, passa-alto, passa-banda, elimina-banda).
* **Cosa disegnare**: il VNA con **P1 e P2**; il **filtro** in mezzo, con l'**ingresso** collegato a **P1** e l'**uscita**
  collegata a **P2**, ciascuno con un cavetto di test.
* **Dettagli**: **ingresso (IN)** e **uscita (OUT)** del filtro indicati chiaramente (il filtro è un dispositivo
  direzionale: l'utente deve sapere quale lato va su P1). Il simbolo del filtro può essere il classico riquadro con la
  curva (non scegliere il tipo: vale per tutti e quattro).

## 7. Attenuatore

* **File**: `attenuator`
* **Cartella**: `ola/modules/attenuator/`
* **Quando si vede**: misura di un attenuatore (fisso o un gradino di uno a gradini).
* **Cosa disegnare**: come il filtro, ma con il **simbolo di un attenuatore** (il riquadro con la barra diagonale o la
  resistenza "a T/pi greco"): **P1** all'ingresso, **P2** all'uscita, con i cavetti di test.
* **Dettagli**: **non esagerare con i colori**: è una cosa semplice, due fili e il dispositivo. Se fai l'immagine del
  filtro prima, questa viene quasi uguale: va bene (cambia solo il simbolo).

## 8. Amplificatore, collegamento diretto

* **File**: `amplifier`
* **Cartella**: `ola/modules/amplifier/`
* **Quando si vede**: misura dell'amplificatore **senza** attenuatore in ingresso.
* **Cosa disegnare**: il VNA con **P1 e P2**; l'**amplificatore** al centro con **IN** collegato a **P1** e **OUT**
  collegato a **P2**; in più l'**alimentazione dell'amplificatore** (un alimentatore o una batteria disegnata a parte,
  con **+ in rosso** e **− in blu**) che va ai suoi **piedini di alimentazione**.
* **Dettagli**: l'**alimentazione ben evidente**, perché l'amplificatore **non funziona** senza; un **simbolo di
  attenzione** (triangolo) o un'etichetta **MAX IN** sull'ingresso del VNA collegato all'uscita dell'amplificatore, per
  ricordare di controllare la potenza massima.

## 9. Amplificatore con attenuatore in ingresso

* **File**: `amplifier_with_attenuator`
* **Cartella**: `ola/modules/amplifier/`
* **Quando si vede**: quando il file di misura ha `input_attenuation_db` (un attenuatore davanti all'amplificatore).
* **Cosa disegnare**: come l'immagine 8, ma tra **P1** e l'ingresso dell'amplificatore c'è l'**attenuatore**:
  P1 → attenuatore → IN dell'amplificatore. L'uscita dell'amplificatore va, come prima, a **P2**.
* **Dettagli**: l'attenuatore con il **simbolo dell'immagine 7**; scrivi **"dB"** (senza numero: il valore dipende dal
  file) o lascia vuoto. L'attenuatore deve essere **incluso nella calibrazione** (un cenno: il piano di calibrazione
  è dopo di lui, o una riga che lo contiene).

## 10. Ripple e rumore, solo sonda

* **File**: `ripple`
* **Cartella**: `ola/modules/ripple/`
* **Quando si vede**: misura del ripple **senza** carico elettronico (l'alimentatore ha già il suo carico).
* **Cosa disegnare**: l'**alimentatore (o la scheda) in prova** con la sua **uscita** (+ e −) e il **condensatore di
  uscita** disegnato. Una **sonda** dell'oscilloscopio con la **punta sul +** e la **molla di massa sul −**, **entrambe
  vicinissime al condensatore**; la sonda va a **CH1** dell'oscilloscopio.
* **Dettagli**: **la molla di massa deve essere visibile**, accanto alla punta (è il dettaglio più importante di
  questa misura: un puntale di massa lungo mostra falsi picchi). Meglio un **ingrandimento** (un cerchio con zoom) sul
  punto della sonda sul condensatore. Aggiungi la scritta **20 MHz** (limite di banda) vicino all'oscilloscopio.

## 11. Ripple e rumore, con carico

* **File**: `ripple_with_load`
* **Cartella**: `ola/modules/ripple/`
* **Quando si vede**: quando il file di misura ha le **correnti di carico** (`conditions`): il programma accende il
  carico elettronico.
* **Cosa disegnare**: come l'immagine 10, ma con in più il **carico elettronico**, collegato all'uscita dell'alimentatore
  (**+ con +**, **− con −**) con **cavi corti e grossi**.
* **Dettagli**: i **cavi del carico** disegnati **spessi** e diversi dalla sonda, per non confonderli; **la sonda resta
  sul condensatore**, non sul carico.

## 12. Efficienza

* **File**: `efficiency`
* **Cartella**: `ola/modules/efficiency/`
* **Quando si vede**: misura dell'efficienza (ingresso, uscita, carico, datalogger). Una sola immagine per tutti i casi,
  quindi **generica**.
* **Cosa disegnare**: da sinistra a destra: l'**alimentatore d'ingresso**, il **convertitore in prova**, il **carico
  elettronico**. Tra l'alimentatore e il convertitore uno **shunt** in serie sul positivo (per misurare la corrente
  d'ingresso). Il **datalogger** sotto, con tre fili che vanno a: **la tensione d'ingresso** (a monte dello shunt,
  vicino all'ingresso del convertitore), **i capi dello shunt** (corrente d'ingresso) e **la tensione d'uscita** (ai
  capi del carico o all'uscita del convertitore).
* **Dettagli**: etichette corte e uguali in tutte le lingue: **VIN**, **IIN**, **VOUT**, **GND**; **non scrivere i
  numeri dei canali** del datalogger: cambiano da un file all'altro (li dice la lista numerata, scritta dal file).
  Un **alimentatore ausiliario** (per il controllo del convertitore) disegnato **tratteggiato**, perché non c'è
  sempre.

## 13. Regolazione di linea e di carico

* **File**: `regulation`
* **Cartella**: `ola/modules/regulation/`
* **Quando si vede**: misura della regolazione di linea e di carico di un convertitore (una sola immagine per tutti i casi).
* **Cosa disegnare**: da sinistra a destra: l'**alimentatore** (con **+ in rosso** e **− in blu**) che va all'**ingresso**
  del **convertitore in prova**; l'**uscita** del convertitore va al **carico elettronico** (cavi **corti e spessi**) e,
  con fili **sottili**, al **voltmetro** (o a un canale del **datalogger**).
* **Dettagli**: i fili sottili del voltmetro **attaccati ai morsetti d'uscita del convertitore**, non in fondo ai cavi del
  carico (la caduta nei cavi non è regolazione); se vuoi, un **secondo filo sottile** dal voltmetro ai **morsetti
  d'ingresso** (tratteggiato: serve solo se si legge anche l'ingresso). Etichette corte: **VIN**, **VOUT**, **GND**.

---

# Foglio di controllo

Spunta man mano. Il file va nella cartella indicata.

- [ ] 1. `cable_transmission` — `ola/modules/cable/`
- [ ] 2. `cable_reflection_open` — `ola/modules/cable/`
- [ ] 3. `cable_reflection_short` — `ola/modules/cable/`
- [ ] 4. `return_loss` — `ola/modules/return_loss/`
- [ ] 5. `antenna` — `ola/modules/antenna/`
- [ ] 6. `filter` — `ola/modules/filter/`
- [ ] 7. `attenuator` — `ola/modules/attenuator/`
- [ ] 8. `amplifier` — `ola/modules/amplifier/`
- [ ] 9. `amplifier_with_attenuator` — `ola/modules/amplifier/`
- [ ] 10. `ripple` — `ola/modules/ripple/`
- [ ] 11. `ripple_with_load` — `ola/modules/ripple/`
- [ ] 12. `efficiency` — `ola/modules/efficiency/`
- [ ] 13. `regulation` — `ola/modules/regulation/`

## Un'idea per fare meno lavoro

Fai prima **una sola immagine di base per il VNA** (le due porte, i cavetti di test, la linea del piano di calibrazione):
si riusa nelle immagini 1-9. Cambia solo il dispositivo in mezzo.

Il **time log** non ha immagine: i suoi collegamenti dipendono dal file (la lista numerata dice cosa collegare).

## Quando una nuova misura ha bisogno di un'immagine

Ogni misura che si aggiunge in futuro elenca le sue immagini nel proprio `wiring.json`, e questo file va aggiornato
con la sua scheda (nome, quando si vede, cosa disegnare).
