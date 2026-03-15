# Auto Lezioni – Uninettuno (helper locale)

Questo progetto apre un browser **visibile** sul desktop secondario e aiuta a:
- mantenere la riproduzione attiva
- cliccare su **"Successiva"** quando la lezione finisce
- registrare log/screenshot in caso di problemi

> Nota: usa questo strumento in modo conforme ai Termini del sito e alle regole del tuo corso.

## Requisiti
- Python 3.11 o 3.12 (consigliato 3.11)
- Playwright

## Installazione (Linux e Windows)

### Opzione consigliata (Linux): automatico
Il comando sotto fa tutto in automatico (installa uv, crea la venv, installa dipendenze, prova a installare Chromium):
```bash
./run_linux.sh
```

1) Crea e attiva un virtualenv

Linux:
```bash
python -m venv .venv
source .venv/bin/activate
```

Windows (PowerShell):
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2) Installa dipendenze
```bash
pip install -r requirements.txt
```

3) Installa il browser di Playwright
```bash
python -m playwright install
```

## Configurazione
Copia il file di esempio e modifica i selettori:
```bash
cp config.example.json config.json
```

Apri `config.json` e imposta:
- `start_url`: la pagina della lezione
- `next_button_selector`: selettore del pulsante "Successiva"
- `tabs_count`: valore di default per quante lezioni vuoi guardare (verra' chiesto all'avvio). Usa `max`/`0` per tutte.
- `max_tabs_per_batch`: massimo numero di tab aperte insieme (default 10)
- `video_ready_timeout_ms`: attesa massima per considerare il video pronto dopo l'apertura
- `next_click_retries`: numero di tentativi aggiuntivi per il click su "Successiva"
- `browser_executable_path` (opzionale): percorso del browser di sistema (se vuoto, prova ad auto-rilevare)
- `video_selector` (opzionale): selettore del tag video
- `logout_check_selector` (opzionale): qualcosa che appare quando sei disconnesso

### Come trovare i selettori
- Apri la pagina in Chrome/Brave/Edge
- Tasto destro sul pulsante **Successiva** → **Ispeziona**
- Copia un selettore CSS stabile (es: `button.next-lesson`)

## Avvio
Linux (automatico, senza attivare la venv):
```bash
./run_linux.sh
```

Windows (PowerShell, automatico):
```powershell
.\run_windows.ps1
```

## Nota per Arch/CachyOS
Playwright su Arch/CachyOS scarica spesso browser "fallback" e può mancare qualche libreria.
La soluzione più semplice è usare il Chromium di sistema:

```bash
sudo pacman -S chromium
```

Poi in `config.json` imposta:
```json
"browser_executable_path": "/usr/bin/chromium"
```

Alla prima esecuzione:
- Il browser si aprirà **visibile**
- Effettua il login manualmente
- Torna al terminale e premi **Invio** per iniziare l'automazione

## Note utili
- I dati di sessione vengono salvati in `./user_data/` (non cancellare se vuoi restare loggato)
- L'automazione non preme piu' "Successiva" a fine lezione: mantiene fino a `max_tabs_per_batch` tab aperte e ne apre una nuova quando una finisce.
- Se scegli `max`, continuerà ad aprire lezioni finché "Successiva" è disponibile.
- I log sono in `./logs/`
- Screenshot automatici (se abilitati) in `./screenshots/`

Se vuoi, possiamo aggiungere notifiche desktop, o farlo girare headless con monitoraggio.
