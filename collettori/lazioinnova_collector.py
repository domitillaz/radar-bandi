"""Collettore Lazio Innova -> bandi.json

Regola: nessun valore "confermato" senza una citazione trovata alla lettera nel testo.
ATTENZIONE: i selettori HTML sono scritti sulla base del testo della pagina, non del
suo codice. Al primo avvio controlla a mano che l'elenco estratto corrisponda al sito.
Richiede: pip install requests beautifulsoup4
"""
import datetime as dt
import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ELENCO_URL = "https://www.lazioinnova.it/bandi-aperti/"
MESI = {m: i for i, m in enumerate(
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split(), 1)}
DATA_RE = re.compile(r"(\d{1,2})\s*°?\s+(" + "|".join(MESI) + r")\s+(\d{4})", re.I)
DURATA_RE = re.compile(r"durata[^.\n]{0,80}?(\d+)\s*(mesi|anni)", re.I)


def scarica(url):
    r = requests.get(url, timeout=30, headers={"User-Agent": "radar-bandi/0.1 (ricerca universitaria)"})
    r.raise_for_status()
    return r.text


def pulisci(s):
    return " ".join(s.split())


def testo(html):
    return pulisci(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))


def testo_pagina(html):
    """Testo del contenuto principale: toglie menu, intestazioni e piè di pagina.
    Se il risultato è troppo corto (struttura insolita) usa tutto il testo della pagina.
    Non si tolgono i <form>: nelle pagine .aspx avvolgono l'intero contenuto."""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    completo = pulisci((soup.body or soup).get_text(" ", strip=True))
    for t in soup(["nav", "header", "footer", "aside"]):
        t.decompose()
    nodo = soup.find("main") or soup.find("article") or soup.body or soup
    t = pulisci(nodo.get_text(" ", strip=True))
    return t if len(t) >= 300 else completo


def campo(valore, stato, citazione=None, motivo=None):
    return {"valore": valore, "stato": stato, "citazione": citazione, "motivo": motivo}


def verifica(c, pagina):
    """Se la citazione non esiste alla lettera nel testo, il campo non può essere confermato."""
    if c["stato"] == "confermato" and (not c["citazione"] or c["citazione"] not in pagina):
        return campo(c["valore"], "da_verificare", None, "Citazione non trovata nel testo")
    return c


def scadenza(frase):
    """Le date sono lette con una regex, non interpretate dal modello."""
    trovate = [(m, dt.date(int(m.group(3)), MESI[m.group(2).lower()], int(m.group(1))))
               for m in DATA_RE.finditer(frase)]
    if not trovate:
        if "esaurimento" in frase.lower():
            return campo(None, "da_verificare", None, "Sportello fino a esaurimento risorse, nessuna data")
        return campo(None, "non_presente", None, "Nessuna data nel testo dell'elenco")
    m, d = trovate[-1]
    cit = frase[max(0, m.start() - 40):m.end()]
    if len(trovate) > 1:
        return campo(d.isoformat(), "da_verificare", cit, "Più date nel testo: verificare quale è la chiusura")
    return campo(d.isoformat(), "confermato", cit)


def durata(scheda):
    m = DURATA_RE.search(scheda)
    if not m:
        return campo(None, "non_presente", None, "Durata non trovata nella scheda")
    return campo(f"{m.group(1)} {m.group(2)}", "confermato", m.group(0))


def estrai_elenco(html):
    soup = BeautifulSoup(html, "html.parser")
    for p in soup.find_all(["p", "li"]):
        b = p.find(["strong", "b"])
        if not b:
            continue
        a = p.find("a", href=True)
        yield pulisci(b.get_text()).rstrip(":"), pulisci(p.get_text(" ", strip=True)), (a["href"] if a else None)


def main():
    oggi = dt.date.today().isoformat()
    html = scarica(ELENCO_URL)
    pagina = testo(html)
    bandi = []
    for titolo, resto, link in estrai_elenco(html):
        url = urljoin(ELENCO_URL, link) if link else ELENCO_URL
        scheda = ""
        if link:
            try:
                scheda = testo_pagina(scarica(url))
            except requests.RequestException:
                pass
        bandi.append({
            "canale": "Regionale", "ente": "Regione Lazio / Lazio Innova",
            "titolo": titolo, "url": url, "data_lettura": oggi,
            "scadenza": verifica(scadenza(resto), pagina),
            "durata": verifica(durata(scheda), scheda) if scheda
                      else campo(None, "da_verificare", None, "Scheda non raggiungibile"),
            # Prossimo passo: estrazione di budget e destinatari con LLM + stessa verifica delle citazioni
            "budget": campo(None, "non_presente"),
            "ammissibilita": campo(None, "non_presente"),
            "testo_fonte": (scheda or resto)[:8000],  # serve all'agente di rilevanza
            "rilevanza": None,
        })
    if not bandi:
        raise SystemExit("Nessun bando estratto: la struttura della pagina potrebbe essere cambiata.")
    with open("bandi.json", "w", encoding="utf-8") as f:
        json.dump({"generato": oggi, "bandi": bandi}, f, ensure_ascii=False, indent=2)
    print(f"{len(bandi)} bandi scritti in bandi.json")


if __name__ == "__main__":
    main()
