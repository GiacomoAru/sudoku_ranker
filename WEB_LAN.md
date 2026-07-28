# Interfaccia web LAN

La web app consente di inviare un Sudoku, salvarlo con nomenclatura standard e
ricevere il JSON dell'analisi, il grafico della catena, la heatmap e il player
passo-passo della soluzione.

Il riepilogo mostra separatamente SE massimo, stima HoDoKu e perceived
difficulty su scala 1–10. Anche ogni passaggio del player riporta il proprio
contributo HoDoKu.

Il server usa `archives/online/`; notebook e script usano per default
`archives/offline/`. I due archivi restano quindi separati.

## 1. Preparazione

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

## 6. Porta e indirizzo personalizzati

`run_web.py` legge queste variabili:

```powershell
$env:SUDOKU_WEB_HOST = "0.0.0.0"
$env:SUDOKU_WEB_PORT = "8000"
.\.venv\Scripts\python.exe run_web.py
```

Gli script in `scripts/` gestiscono intenzionalmente la porta predefinita
8000. Se la cambi, gestisci il processo in primo piano con `Ctrl+C`.

## 7. API disponibili

- `GET /api/v1/health`
- `POST /api/v1/analyses`
- `POST /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `GET /api/v1/analyses/{puzzle_id}/plots/difficulty-chain.png`
- `GET /api/v1/analyses/{puzzle_id}/plots/technique-heatmap.png`

La richiesta richiede `grid`, `provenience`, `tag` e `difficulty`. Il Sudoku
viene salvato tramite `save_with_standard_nomenclature`; l'analisi predefinita
è `profile` con finestra `3.0`.

La pagina usa una coda asincrona: le richieste HTTP continuano a rispondere
mentre un singolo worker esegue le analisi. La coda contiene al massimo 16
job. Questa serializzazione protegge l'attuale archivio JSON; un futuro pool
di processi richiederà anche una persistenza transazionale.

## 8. Limite di sicurezza attuale

Questa configurazione è pensata per la rete domestica fidata. Non configurare
port forwarding verso Internet: al momento non ci sono autenticazione, TLS,
rate limiting né protezione da upload ostili. La pubblicazione online andrà
fatta dietro un reverse proxy HTTPS e dopo aver aggiunto autenticazione.
