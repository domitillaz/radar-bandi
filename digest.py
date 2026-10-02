"""Legge data/bandi*.json e scrive digest.md, data/stato.json e data/visti.json.
Regole: nessun allarme di scadenza se la scadenza non è 'confermato'; i problemi di
copertura (collettori falliti, errori) compaiono sempre nel digest."""
import datetime as dt
import glob
import json
import os

SOGLIA = 6
GIORNI_ALLERTA = {30, 14, 7, 1}
oggi = dt.date.today()


def punteggio(b):
    return (b.get("rilevanza") or {}).get("punteggio")


def giorni(b):
    s = b.get("scadenza") or {}
    if s.get("stato") == "confermato" and s.get("valore"):
        return (dt.date.fromisoformat(s["valore"]) - oggi).days
    return None


def riga(b):
    s = b.get("scadenza") or {}
    if giorni(b) is not None:
        quando = f"scadenza {s['valore']} (tra {giorni(b)} giorni)"
    else:
        quando = "scadenza DA VERIFICARE" + (f": {s['motivo']}" if s.get("motivo") else "")
    p = punteggio(b)
    return f"- [{b['titolo']}]({b['url']}) ({b['canale']}, rilevanza {p if p is not None else 'n/d'}/10): {quando}"


files = sorted(glob.glob("data/bandi*.json"))
bandi, errori = [], []
for f in files:
    d = json.load(open(f, encoding="utf-8"))
    bandi += d["bandi"]
    errori += d.get("errori", [])
falliti = []
if os.path.exists("data/falliti.txt"):
    falliti = [x.strip() for x in open("data/falliti.txt", encoding="utf-8") if x.strip()]

visti_path = "data/visti.json"
visti = set(json.load(open(visti_path, encoding="utf-8"))) if os.path.exists(visti_path) else set()
chiave = lambda b: f"{b['canale']}|{b['titolo']}"
aperti = [b for b in bandi if giorni(b) is None or giorni(b) >= 0]
rilevanti = [b for b in aperti if (punteggio(b) or -1) >= SOGLIA]

urgenti = [b for b in rilevanti if giorni(b) in GIORNI_ALLERTA]
nuovi = [b for b in rilevanti if chiave(b) not in visti]
da_ver = [b for b in rilevanti if giorni(b) is None]
non_val = [b for b in aperti if punteggio(b) is None]

L = [f"# Radar bandi, {oggi.isoformat()}", ""]
if falliti or errori:
    L += ["## Copertura incompleta", "Questi problemi significano che alcuni bandi potrebbero mancare:"]
    L += [f"- fonte non aggiornata: {x}" for x in falliti] + [f"- {x}" for x in errori] + [""]
for titolo, lista in [("Scadenze imminenti (date confermate)", urgenti),
                      (f"Nuovi bandi con rilevanza almeno {SOGLIA}", nuovi),
                      ("Rilevanti con scadenza da verificare", da_ver)]:
    L += [f"## {titolo}"] + ([riga(b) for b in lista] if lista else ["Nessuno."]) + [""]
L += [f"## Non valutati ({len(non_val)})",
      "Testo della fonte insufficiente o valutazione non verificabile: nessun punteggio assegnato."]
L += [f"- {b['titolo']}" for b in non_val[:15]] + ([f"- e altri {len(non_val) - 15}"] if len(non_val) > 15 else [])

open("digest.md", "w", encoding="utf-8").write("\n".join(L) + "\n")
json.dump(sorted(visti | {chiave(b) for b in bandi}), open(visti_path, "w", encoding="utf-8"), ensure_ascii=False)
json.dump({"aggiornato": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "falliti": falliti,
           "file": [os.path.basename(f) for f in files]},
          open("data/stato.json", "w", encoding="utf-8"), ensure_ascii=False)

invia = bool(urgenti) or oggi.weekday() == 0 or os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
if os.environ.get("GITHUB_OUTPUT"):
    open(os.environ["GITHUB_OUTPUT"], "a").write(f"invia={'true' if invia else 'false'}\n")
print(f"{len(bandi)} bandi, {len(rilevanti)} rilevanti, {len(urgenti)} urgenti, {len(falliti)} fonti fallite")
