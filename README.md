# Radar bandi

Pipeline notturna: collettori (Lazio Innova, Funding & Tenders Portal) → rilevanza (modello se c'è la chiave, altrimenti parole chiave) → digest → dashboard su GitHub Pages.

## Messa in funzione
1. Crea un repository su GitHub e carica il contenuto di questa cartella.
2. (Facoltativo, a pagamento) Settings → Secrets and variables → Actions → New repository secret: `ANTHROPIC_API_KEY`. **Senza questo secret la pipeline è completamente gratuita** e calcola la pertinenza con `filtro_parole_chiave.py`.
3. Settings → Pages → Source: **GitHub Actions**.
4. Tab Actions → "Aggiorna radar bandi" → Run workflow. Il primo giro apre anche un issue col digest.
5. Controlla il log di ogni collettore: i selettori e i nomi dei campi non sono mai stati provati sui siti reali.

## Attenzione
- Con un repository pubblico, dashboard e dati sono pubblici (compresi i temi del profilo). GitHub Pages privato richiede un piano Enterprise.
- GitHub può disattivare i workflow schedulati dopo 60 giorni di inattività del repository: se smette di girare, riattivalo da Actions.
- Solo se imposti `ANTHROPIC_API_KEY`: la chiamata all'API di Claude è a pagamento. La cache (`data/rilevanza_cache.json`) evita di rivalutare bandi invariati.

## Aggiungere un canale
1. Scrivi `collettori/<nome>_collector.py` che produce `bandi_<nome>.json` con lo stesso schema (campi con `valore`, `stato`, `citazione`, più `testo_fonte`).
2. Aggiungi `<nome>` all'elenco nel ciclo "Collettori" di `.github/workflows/aggiorna.yml`.
La dashboard carica da sola tutti i file `bandi*.json`.

## Notifiche
`digest.py` apre un issue (GitHub ti manda l'email) ogni lunedì, a ogni avvio manuale e quando una scadenza **confermata** di un bando con rilevanza ≥ 6 è a 30, 14, 7 o 1 giorno. Le scadenze "da verificare" non generano mai allarmi urgenti.
