"""Estrae dal testo_fonte di ogni bando i dettagli che i collettori non hanno trovato.

Regole (stesso vincolo di non inventare):
- scadenza (solo canali non europei): una data conta solo se, nei 90 caratteri che la precedono, c'è una parola di
  scadenza (scadenza, entro, candidature, termine, deadline...). Una sola data così = "confermato"; più date
  diverse = "da_verificare" con la più lontana. Le date di eventi senza parola di scadenza vengono ignorate.
- durata, budget, ammissibilità: compaiono solo con una citazione copiata dal testo. Budget e ammissibilità
  sono sempre "da_verificare": sono letture del testo, non dati ufficiali.
- Non sovrascrive mai un campo già "confermato".
Uso: python arricchisci.py bandi.json bandi_europa.json bandi_mur.json
"""
import argparse
import datetime as dt
import json
import re

MESI = {m: i for i, m in enumerate(
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split(), 1)}
TXT = re.compile(r"(\d{1,2})\s*°?\s+(" + "|".join(MESI) + r")\s+(\d{4})", re.I)
NUM = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
CONTESTO = re.compile(r"scadenz\w*|\bentro\b|candidatur\w*|\btermin\w*|deadline|fino al|chiusura|presentazione delle domande", re.I)
DURATA = re.compile(r"\b(?:durata|duration|lasting|last)\b[^.\n]{0,80}?(\d+)\s*(mesi|anni|months|years)\b", re.I)
IMPORTO = re.compile(r"€\s?\d[\d.,]*|\d[\d.,]*\s?(?:milioni di euro|milioni|mln|euro|€|EUR|million)\b", re.I)
CONTESTO_BUDGET = re.compile(r"dotazione|budget|importo|contribut\w*|stanziament\w*|risorse|finanziament\w*|funding|massim\w*", re.I)
ELIG = re.compile(r"riservat\w+|rivolt\w+|destinatari\w*|beneficiari\w*|possono\s+(?:partecipare|presentare|candidarsi|aderire)|può\s+partecipare|eligible|open to|addressed to", re.I)
IMPRESE = re.compile(r"\b(PMI|piccole e medie imprese|microimprese|imprese|startup|start-up|aziende|SMEs?|companies)\b", re.I)
RICERCA = re.compile(r"\b(universit\w+|enti di ricerca|organismi di ricerca|centri di ricerca|research (?:organi[sz]ations?|institutions?)|higher education)\b", re.I)


def campo(valore, stato, citazione=None, motivo=None):
    return {"valore": valore, "stato": stato, "citazione": citazione, "motivo": motivo}


def data(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def date_nel_testo(t):
    out = [(m.start(), m.end(), data(int(m.group(3)), MESI[m.group(2).lower()], int(m.group(1)))) for m in TXT.finditer(t)]
    out += [(m.start(), m.end(), data(int(m.group(3)), int(m.group(2)), int(m.group(1)))) for m in NUM.finditer(t)]
    return sorted(x for x in out if x[2])


def scadenza_da_testo(t):
    cand = {}
    for s, e, d in date_nel_testo(t):
        base = max(0, s - 90)
        k = list(CONTESTO.finditer(t[base:s]))
        if k:
            cand.setdefault(d, t[base + k[-1].start():e])
    if not cand:
        return None
    if len(cand) == 1:
        d, c = next(iter(cand.items()))
        return campo(d.isoformat(), "confermato", c)
    d = max(cand)
    return campo(d.isoformat(), "da_verificare", cand[d], "Più date con parole di scadenza nel testo: verificare quale vale")


def durata_da_testo(t):
    trovate = {(m.group(1), m.group(2).lower()): m.group(0) for m in DURATA.finditer(t)}
    if not trovate:
        return None
    (n, u), cit = next(iter(trovate.items()))
    if len(trovate) > 1:
        return campo(f"{n} {u}", "da_verificare", cit, "Più durate nel testo")
    return campo(f"{n} {u}", "confermato", cit)


def budget_da_testo(t):
    importi, cit = [], None
    for m in IMPORTO.finditer(t):
        if CONTESTO_BUDGET.search(t[max(0, m.start() - 100):m.start()]):
            importi.append(m.group(0).strip())
            cit = cit or t[max(0, m.start() - 80):m.end()]
    if not importi:
        return None
    return campo(", ".join(dict.fromkeys(importi))[:80], "da_verificare", cit,
                 "Importo letto nel testo: verificare se è totale, per progetto o per impresa")


def ammissibilita_da_testo(t):
    frasi = [f.strip() for f in re.split(r"(?<=[.;!?])\s+", t) if ELIG.search(f)]
    ric = [f for f in frasi if RICERCA.search(f)]
    imp = [f for f in frasi if IMPRESE.search(f)]
    if ric:
        return campo("Cita università o enti di ricerca", "da_verificare", ric[0][:240],
                     "Nominati tra i destinatari: verificare condizioni (consorzio, ruolo)")
    if imp:
        return campo("Solo imprese (probabile)", "da_verificare", imp[0][:240],
                     "Il bando sembra riservato a imprese: probabile esclusione delle università")
    return None


def arricchisci(b):
    t = " ".join((b.get("testo_fonte") or "").split())
    fatto = []
    if not t:
        return fatto
    ex = b.get("scadenza") or campo(None, "non_presente")
    if b.get("canale") != "Europa" and ex["stato"] != "confermato" and not str(ex.get("motivo") or "").startswith("Preannuncio"):
        n = scadenza_da_testo(t)
        if n and n["citazione"] in t and (ex["stato"] == "non_presente" or n["stato"] == "confermato"):
            b["scadenza"] = n
            fatto.append("scadenza")
    for chiave, fn in [("durata", durata_da_testo), ("budget", budget_da_testo), ("ammissibilita", ammissibilita_da_testo)]:
        if (b.get(chiave) or {"stato": "non_presente"})["stato"] == "non_presente":
            n = fn(t)
            if n and n["citazione"] in t:
                b[chiave] = n
                fatto.append(chiave)
    return fatto


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    for f in ap.parse_args().files:
        dati = json.load(open(f, encoding="utf-8"))
        stat = {}
        for b in dati["bandi"]:
            s = stat.setdefault(b.get("canale", "?"), {"n": 0, "testo_corto": 0, "arricchiti": 0})
            s["n"] += 1
            s["testo_corto"] += len(b.get("testo_fonte") or "") < 300
            s["arricchiti"] += bool(arricchisci(b))
        json.dump(dati, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"{f}: {stat}")


if __name__ == "__main__":
    main()
