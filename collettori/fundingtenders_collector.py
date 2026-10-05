"""Collettore Funding & Tenders Portal (UE) -> bandi_europa.json

Usa l'API di ricerca pubblica del portale (apiKey=SEDIA). Non è un'API ufficiale
versionata: endpoint, filtri e nomi dei campi possono cambiare senza preavviso.
ATTENZIONE: i nomi dei campi della risposta (identifier, title, deadlineDate, ...)
sono scritti da documentazione di terzi e non li ho potuti testare: al primo avvio
stampa una risposta grezza (--debug) e confrontala con il parser.
Richiede: pip install requests
"""
import datetime as dt
import json
import re
import sys
import time

import requests

API = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
TOPIC_URL = "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/"
STATI = ["31094501", "31094502"]  # 31094501 = in arrivo, 31094502 = aperto
PAROLE = ["organ-on-chip", "lab-on-chip", "microfluidic", "biosensor", "medical sensor",
          "machine learning health data", "AI medical devices", "in vitro diagnostics",
          "digital twin health", "point-of-care"]
DURATA_RE = re.compile(r"(?:duration|lasting|last)[^.\n]{0,80}?(\d+)\s*(months|years)", re.I)


def campo(valore, stato, citazione=None, motivo=None):
    return {"valore": valore, "stato": stato, "citazione": citazione, "motivo": motivo}


def verifica(c, grezzo):
    """Un campo è 'confermato' solo se la sua prova compare alla lettera nel record scaricato."""
    if c["stato"] == "confermato" and (not c["citazione"] or c["citazione"] not in grezzo):
        return campo(c["valore"], "da_verificare", None, "Prova non trovata nel record")
    return c


def meta(r, chiave):
    v = (r.get("metadata") or {}).get(chiave)
    if isinstance(v, list):
        v = [x for x in v if x not in (None, "")]
        return v
    return [v] if v not in (None, "") else []


def cerca(parola, pagina=1):
    query = {"bool": {"must": [{"terms": {"type": ["1"]}}, {"terms": {"status": STATI}}]}}
    r = requests.post(
        API, params={"apiKey": "SEDIA", "text": parola, "pageSize": 50, "pageNumber": pagina},
        files={"query": (None, json.dumps(query), "application/json"),
               "languages": (None, json.dumps(["en"]), "application/json")},
        headers={"User-Agent": "radar-bandi/0.1 (ricerca universitaria)"}, timeout=60)
    r.raise_for_status()
    return r.json()


def scadenza(r, grezzo):
    raw = meta(r, "deadlineDate")
    date = []
    for s in raw:
        try:
            date.append((s, dt.date.fromisoformat(str(s)[:10])))
        except ValueError:
            pass
    if not date:
        return campo(None, "non_presente", None, "Nessuna deadlineDate nel record (topic in arrivo o a sportello?)")
    if len({d for _, d in date}) > 1:
        s, d = max(date, key=lambda x: x[1])
        return campo(d.isoformat(), "da_verificare", s, "Più scadenze (cut-off multipli o due fasi): verificare quale vale per te")
    ident = str((meta(r, "identifier") or [""])[0]).lower()
    modello = " ".join(str(x) for x in meta(r, "deadlineModel")).lower()
    if "two-stage" in ident or "two-stage" in modello or "two stage" in modello:
        return campo(date[0][1].isoformat(), "da_verificare", date[0][0],
                     "Procedura a due fasi: la data riguarda probabilmente solo la prima fase")
    if "multiple" in modello:
        return campo(date[0][1].isoformat(), "da_verificare", date[0][0], "Più cut-off: verificare quale vale per te")
    return verifica(campo(date[0][1].isoformat(), "confermato", date[0][0]), grezzo)


def testo_topic(r):
    t = re.sub(r"<[^>]+>", " ", " ".join(meta(r, "descriptionByte") + meta(r, "description") + [r.get("summary") or ""]))
    return " ".join(t.split())


def durata(r):
    testo = testo_topic(r)
    m = DURATA_RE.search(testo)
    if not m:
        return campo(None, "non_presente", None, "Durata non indicata nei campi dell'API: leggere la scheda del topic")
    return campo(f"{m.group(1)} {m.group(2)}", "confermato", m.group(0))


def main(debug=False):
    trovati, errori, campi = {}, [], None
    for parola in PAROLE:
        try:
            dati = cerca(parola)
        except (requests.RequestException, ValueError) as e:
            errori.append(f"ricerca '{parola}' non riuscita: {type(e).__name__}")
            continue
        if debug and parola == PAROLE[0]:
            print(json.dumps((dati.get("results") or [])[:1], indent=2, ensure_ascii=False)[:3000])
        if campi is None and dati.get("results"):  # nomi e valori di esempio dei campi, per migliorare il parser
            r0 = dati["results"][0]
            campi = {"_chiavi_record": list(r0.keys()),
                     **{f"metadata.{k}": str(v)[:200] for k, v in (r0.get("metadata") or {}).items()}}
        for r in dati.get("results") or []:
            ident = (meta(r, "identifier") or [r.get("reference")])[0]
            if not ident:
                continue
            voce = trovati.setdefault(ident, {"r": r, "parole": []})
            voce["parole"].append(parola)
        time.sleep(1)
    if campi:
        with open("campi_api.json", "w", encoding="utf-8") as f:
            json.dump(campi, f, ensure_ascii=False, indent=2)
    if not trovati and errori:
        raise SystemExit("Tutte le ricerche sono fallite: " + "; ".join(errori))
    oggi = dt.date.today().isoformat()
    bandi = []
    for ident, v in trovati.items():
        r = v["r"]
        grezzo = json.dumps(r, ensure_ascii=False)
        titolo = (meta(r, "title") or [r.get("title") or ident])[0]
        bandi.append({
            "canale": "Europa", "ente": "Commissione europea (Funding & Tenders Portal)",
            "titolo": f"{ident}: {titolo}", "url": TOPIC_URL + str(ident).lower(), "data_lettura": oggi,
            "trovato_con": v["parole"],
            "scadenza": scadenza(r, grezzo),
            "durata": durata(r),
            # Da implementare: budgetOverview ha una struttura annidata da verificare
            "budget": campo(None, "non_presente", None, "Estrazione del budget non ancora implementata"),
            "ammissibilita": campo(None, "non_presente", None, "Il record non dichiara l'ammissibilità: leggere le condizioni del topic"),
            "testo_fonte": testo_topic(r)[:8000],  # serve all'agente di rilevanza
            "rilevanza": None,
        })
    if not bandi:
        raise SystemExit("Nessun topic trovato: filtri o struttura della risposta potrebbero essere cambiati.")
    with open("bandi_europa.json", "w", encoding="utf-8") as f:
        json.dump({"generato": oggi, "errori": errori, "bandi": bandi}, f, ensure_ascii=False, indent=2)
    print(f"{len(bandi)} topic scritti in bandi_europa.json; errori: {len(errori)}")


if __name__ == "__main__":
    main(debug="--debug" in sys.argv)
