# Interfaccia web: locale, LAN e Internet

La web app consente di inviare un Sudoku, salvarlo con nomenclatura standard e
ricevere il JSON dell'analisi, il grafico della catena, la heatmap e il player
passo-passo della soluzione.

Il riepilogo mostra separatamente Difficoltà Tecnica (SE massimo), Carico di
risoluzione (HoDoKu cumulativo) e Difficoltà percepita sulla scala numerica
SE. Ogni passaggio del player riporta i propri valori. Il server accetta
soltanto Sudoku con soluzione unica e lo indica esplicitamente nel risultato.

Il server usa `archives/online/`; notebook e script usano per default
`archives/offline/`. I due archivi restano quindi separati.

## Accesso rapido da Internet e telefono

La modalità `internet` mantiene FastAPI e l'archivio sul computer, ma apre un
Cloudflare Quick Tunnel HTTPS in uscita. Non richiede port forwarding, IP
pubblico, modifiche al router o una regola firewall in ingresso.

### 1. Installa `cloudflared` senza privilegi amministrativi

Dalla radice del progetto, in PowerShell:

```powershell
New-Item -ItemType Directory -Path .\tools -Force
Invoke-WebRequest `
  -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" `
  -OutFile .\tools\cloudflared.exe
.\tools\cloudflared.exe --version
```

Il file locale è escluso da Git. In alternativa si può installare
`cloudflared` nel sistema oppure indicarne il percorso con
`SUDOKU_CLOUDFLARED_PATH`.

### 2. Scegli una password e avvia

```powershell
$env:SUDOKU_WEB_ACCESS_USERNAME = "sudoku"
$env:SUDOKU_WEB_ACCESS_PASSWORD = "scegli-almeno-12-caratteri"
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\start_web.ps1 -Exposure internet
```

Lo script stampa un valore simile a:

```text
URL PUBBLICO: https://parole-casuali.trycloudflare.com
Utente: sudoku
```

Apri quel link sul telefono. Il browser chiede utente e password una sola
volta e poi mostra l'interfaccia completa, incluso lo scatto dalla fotocamera.
Il telefono può essere sotto rete mobile o qualunque altra Wi-Fi.
Al primissimo tentativo il nuovo indirizzo può richiedere 5-10 secondi per
diventare risolvibile: se non si apre subito, attendi e ricarica la pagina.

Il link casuale cambia a ogni riavvio. È una scelta adatta alla fase attuale:
non serve un account Cloudflare e il sito esiste soltanto mentre server e
tunnel sono attivi. Per un dominio stabile si potrà passare in seguito a un
tunnel nominato senza modificare FastAPI.

Per avviare in background usa:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\start_web.ps1 -Background -Exposure internet
```

Per recuperare nuovamente il link:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\status_web.ps1
```

Per fermare sia FastAPI sia il tunnel:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\stop_web.ps1
```

Esegui `status_web.ps1` e `stop_web.ps1` nello stesso terminale, oppure
reimposta prima le due variabili di autenticazione. La password non viene
scritta su disco.

La modalità si controlla con la variabile chiaramente visibile
`EXPOSURE_MODE` in `run_web.py`, oppure senza modificare file tramite:

```powershell
$env:SUDOKU_WEB_EXPOSURE = "internet"  # local | lan | internet
.\.venv\Scripts\python.exe run_web.py
```

Documentazione ufficiale:

- [Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)
- [Download di cloudflared](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/downloads/)

## 1. Preparazione locale

Apri PowerShell nella radice del progetto:

```powershell
cd C:\Users\cicci\Desktop\workspaces\sudoku
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 2. Avvio consigliato: primo piano

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_web.ps1
```

Il terminale rimane occupato intenzionalmente perché mostra i log del server.
Non è un blocco: finché il server gira, quel comando non deve terminare. Apri
un altro terminale per gli altri comandi. Per fermarlo premi `Ctrl+C`.

In alternativa, il comando Python equivalente è:

```powershell
.\.venv\Scripts\python.exe run_web.py
```

## 3. Avvio in background

Quando non vuoi lasciare aperto il terminale:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_web.ps1 -Background
```

Lo script restituisce il PID solo dopo che `/api/v1/health` ha risposto. Non
concatena arresto, attese, redirect e nuovo avvio nella stessa riga: sono
operazioni separate e verificabili.

Stato:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\status_web.ps1
```

Arresto sicuro:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop_web.ps1
```

Lo script di arresto controlla l'endpoint health specifico dell'app, il
profilo archivio `online`, il proprietario della porta 8000 e il tipo di
processo prima di terminarlo, senza richiedere privilegi amministrativi.

## 4. Accesso dal computer server

Apri:

```text
http://127.0.0.1:8000
```

Controllo rapido da PowerShell:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

Documentazione interattiva delle API:

```text
http://127.0.0.1:8000/docs
```

## 5. Accesso da telefono, tablet o altro computer

1. Collega entrambi i dispositivi alla stessa rete Wi-Fi/LAN.
2. Sul computer server esegui `ipconfig`.
3. Cerca `Indirizzo IPv4` nella scheda Wi-Fi o Ethernet attiva, per esempio
   `192.168.1.42`.
4. Sul secondo dispositivo apri `http://192.168.1.42:8000`.

Non usare l'indirizzo di una scheda disconnessa, di una VPN o di un adattatore
virtuale. Il server ascolta su `0.0.0.0`, quindi accetta connessioni dalle
interfacce di rete del computer.

### Firewall Windows

Al primo avvio Windows può chiedere l'autorizzazione per Python: consenti
l'accesso alle **reti private**, non è necessario abilitarlo sulle reti
pubbliche.

Se il prompt non compare, crea una regola in:

`Sicurezza di Windows` → `Firewall e protezione della rete` →
`Impostazioni avanzate` → `Regole connessioni in entrata`.

Consenti TCP sulla porta `8000` per il profilo **Privato**. Potrebbero servire
privilegi amministrativi.

### Se da un altro dispositivo non si apre

- verifica che `scripts/status_web.ps1` riporti `status: ok`;
- prova prima `http://127.0.0.1:8000` sul computer server;
- verifica che l'IP non sia cambiato dopo una riconnessione Wi-Fi;
- disattiva temporaneamente la VPN;
- evita una rete guest: molti router isolano i dispositivi client;
- controlla che la rete Windows sia classificata come privata;
- prova `Test-NetConnection IP-DEL-SERVER -Port 8000` da un altro PC Windows.

## 6. Modalità, porta e indirizzo personalizzati

`run_web.py` legge queste variabili:

```powershell
$env:SUDOKU_WEB_EXPOSURE = "lan"
$env:SUDOKU_WEB_HOST = "0.0.0.0"
$env:SUDOKU_WEB_PORT = "8000"
.\.venv\Scripts\python.exe run_web.py
```

I valori di `SUDOKU_WEB_EXPOSURE` sono:

- `local`: soltanto il computer server, su `127.0.0.1`;
- `lan`: rete domestica, su `0.0.0.0`;
- `internet`: HTTPS pubblico tramite tunnel, con origine vincolata a
  `127.0.0.1`.

Gli script in `scripts/` rispettano anche `SUDOKU_WEB_PORT`.

## 7. API disponibili

- `GET /api/v1/health`
- `POST /api/v1/analyses`
- `POST /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `POST /api/v1/photos/recognise`
- `GET /api/v1/photos/{photo_id}/original`
- `GET /api/v1/photos/{photo_id}/rectified`
- `GET /api/v1/analyses/{puzzle_id}/plots/difficulty-chain.png`
- `GET /api/v1/analyses/{puzzle_id}/plots/technique-heatmap.png`

La richiesta richiede `grid`, `provenience`, `tag` e `difficulty`. Il Sudoku
viene salvato tramite `save_with_standard_nomenclature`; l'analisi predefinita
è `profile` con finestra `3.0`.

La pagina usa una coda asincrona: le richieste HTTP continuano a rispondere
mentre un singolo worker esegue le analisi. La coda contiene al massimo 16
job. Questa serializzazione protegge l'attuale archivio JSON; un futuro pool
di processi richiederà anche una persistenza transazionale.

## 8. Riconoscimento Sudoku da foto

Dalla sezione **Foto OCR** puoi scattare una foto con il telefono oppure
scegliere un file JPEG, PNG o WebP fino a 12 MB. Il riconoscimento avviene
interamente sul computer server:

1. viene individuato il bordo esterno del Sudoku;
2. la prospettiva viene corretta;
3. le 81 celle vengono segmentate e classificate;
4. la griglia riconosciuta viene riportata negli input modificabili;
5. le celle a bassa confidenza sono evidenziate in arancione.

Prima di premere **Analizza e salva**, confronta sempre la griglia con
l'anteprima raddrizzata. Correggendo gli input e inviando il Sudoku, la foto
viene marcata come confermata e collegata alla griglia corretta.

Le immagini non finiscono nei JSON dei puzzle. Sono conservate separatamente:

```text
archives/online/photos/<photo_id>/
    original.jpg       file ricevuto, estensione variabile
    rectified.png      griglia corretta prospetticamente
    metadata.json      OCR, confidenze, stato e revisione umana
```

Anche gli upload in cui la griglia non viene trovata sono conservati con stato
`failed`: sono esempi utili per migliorare in seguito il rilevatore. Dopo la
conferma, `metadata.json` contiene la coppia fra foto e griglia revisionata,
adatta alla costruzione di un dataset supervisionato.

Per risultati migliori:

- inquadra tutto il bordo esterno;
- evita ombre nette, riflessi e pieghe della carta;
- usa una risoluzione sufficiente, senza zoom digitale eccessivo;
- preferisci una ripresa quasi frontale;
- verifica soprattutto cifre stampate con font insoliti.

Le immagini ad alta risoluzione fino a 12000 px per lato vengono conservate
nel formato originale e ridimensionate soltanto in memoria per l'elaborazione.
Il rilevatore prova prima il bordo quadrangolare classico; sulle pagine curve
usa come fallback la periodicità delle dieci linee orizzontali e verticali.

Per riprovare le foto fallite dopo un aggiornamento dell'algoritmo:

```powershell
# anteprima senza modificare l'archivio
.\.venv\Scripts\python.exe .\scripts\reprocess_photos.py

# applica i nuovi risultati, conservando lo storico dei tentativi
.\.venv\Scripts\python.exe .\scripts\reprocess_photos.py --apply
```

API aggiuntive:

- `POST /api/v1/photos/recognise`
- `GET /api/v1/photos/{photo_id}/original`
- `GET /api/v1/photos/{photo_id}/rectified`

L'endpoint di analisi accetta il campo opzionale `photo_id`, usato per
registrare la griglia corretta e collegarla al puzzle salvato.

## 9. Privacy e sicurezza

Non configurare port forwarding verso Internet. La modalità `internet`
mantiene l'origine in ascolto soltanto su `127.0.0.1`, usa HTTPS sul tratto
pubblico e richiede una password di almeno 12 caratteri. Tutte le route,
incluse API, immagini e documentazione, sono protette.

Usa una password unica, non condividere pubblicamente il link e arresta il
tunnel quando non serve. Quick Tunnel è indicato da Cloudflare per test e
sviluppo, senza garanzie di disponibilità: per un servizio permanente servirà
un tunnel nominato, idealmente con Cloudflare Access, dominio stabile e
monitoraggio. L'attuale coda limita comunque a un worker le analisi e
Cloudflare applica i propri limiti alle richieste concorrenti.

Le foto possono contenere sfondo e dettagli dell'ambiente. Rimangono sul
computer server e `archives/` è esclusa da Git, ma vanno comunque considerate
dati personali: prima di condividere backup o dataset, ritaglia o elimina le
immagini non necessarie.
