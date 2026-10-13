"""Collettore MIMIT (Ministero delle Imprese e del Made in Italy) -> bandi_mimit.json

Legge gli elenchi "incentivi in gestione" e "incentivi in evidenza", apre la scheda di ogni incentivo e tiene
solo quelli con un contenuto di ricerca (ricerca industriale, sviluppo sperimentale, organismi di ricerca,
università, IPCEI, Chips...). Scarta i bonus per consumatori e simili, e gli incentivi già chiusi.

Regole:
- La scadenza viene letta solo dalle frasi che parlano di scadenza/chiusura/termini ("si sono chiusi il...",
  "dal ... al ...", "entro il ..."). Una data confermata ha sempre la citazione letterale. Più date diverse
  = "da_verificare". Nessuna data = "da_verificare" (misura chiusa o a sportello continuo: non lo si sa).
- Il filtro di rilevanza dà un punteggio fisso ai bandi con ente "MIMIT" che parlano di ricerca generica: i bandi
  per imprese con attività di ricerca non hanno parole chiave biomediche, ma l'università può parteciparvi come partner.
ATTENZIONE: il codice HTML del sito non è stato verificato, e il parametro ?limit=100 (100 schede per pagina)
è un'ipotesi: se non funziona il collettore usa la pagina semplice e segue i link di paginazione.
Richiede: pip install requests beautifulsoup4
"""
import datetime as dt
import json
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://www.mimit.gov.it"
LISTE = [BASE + "/it/incentivi-mise/incentivi-in-gestione", BASE + "/it/incentivi-mise/incentivi-in-evidenza"]
MAX_PAGINE_LISTA = 12
MAX_SCHEDE = 150
MESI = {m: i for i, m in enumerate(
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split(), 1)}
MESE_RE = "|".join(MESI)
TXT = re.compile(rf"(\d{{1,2}})\s*°?\s+({MESE_RE})\s+(\d{{4}})", re.I)
NUM = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
PARTNER = re.compile(r"ricerca\s+industriale|sviluppo\s+sperimentale|organismi?\s+di\s+ricerca|co-?proponent\w*"
                     r"|universit\w+|centri\s+di\s+ricerca", re.I)
RICERCA = re.compile(PARTNER.pattern + r"|ricerca\s+e\s+sviluppo|\bR&S\b|\bHorizon\b|orizzonte\s+europa"
                     r"|tecnologie\s+abilitanti|\bKETs\b|\bIPCEI\b|\bChips\b|semiconduttor\w+", re.I)
FRASE_SCAD = re.compile(r"chius\w*|scad\w*|\bentro\b|sino\s+al|fino\s+al|\bdal\b[^.;]{0,80}\bal\b", re.I)
INTERVALLO = re.compile(r"\b(?:dal|dalle|da)\b.*\b(?:al|alle|sino\s+al|fino\s+al)\b", re.I)
CHIUSO = re.compile(r"(?:termini|domande|sportello|bando|avviso|presentazione)[^.]{0,100}"
                    r"\b(?:si\s+sono\s+chius\w+|(?:è|sono)\s+(?:stat\w+\s+)?chius\w+|chiuso)\b", re.I)


def pulisci(s):
    return " ".join(s.split())


def scarica(url):
    r = requests.get(url, timeout=30, headers={"User-Agent": "radar-bandi/0.1 (ricerca universitaria)"})
    r.raise_for_status()
    return r.text


def campo(valore, stato, citazione=None, motivo=None):
    return {"valore": valore, "stato": stato, "citazione": citazione, "motivo": motivo}


def testo_pagina(html):
    """Testo del contenuto principale (senza menu e piè di pagina); se troppo corto usa tutto il testo."""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    completo = pulisci((soup.body or soup).get_text(" ", strip=True))
    for t in soup(["nav", "header", "footer", "aside"]):
        t.decompose()
    nodo = soup.find("main") or soup.find("article") or soup.body or soup
    t = pulisci(nodo.get_text(" ", strip=True))
    return t if len(t) >= 300 else completo


def data(y, m, d):
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def date_nel_testo(t):
    out = [(m.start(), m.end(), data(int(m.group(3)), MESI[m.group(2).lower()], int(m.group(1)))) for m in TXT.finditer(t)]
    out += [(m.start(), m.end(), data(int(m.group(3)), int(m.group(2)), int(m.group(1)))) for m in NUM.finditer(t)]
    return sorted(x for x in out if x[2])


def frasi(testo):
    return re.split(r"(?<=[.;])\s+(?=[A-ZÈÀÌÒÙ“\"(])", testo)


def scadenza(testo):
    """Restituisce (campo, ultima_data|None). Considera solo le frasi che parlano di scadenza/chiusura."""
    trovate = []
    for f in frasi(testo):
        if FRASE_SCAD.search(f):
            ds = date_nel_testo(f)
            for s, e, d in ds:
                trovate.append((d, f[max(0, s - 50):e], len(ds) >= 2 and bool(INTERVALLO.search(f)), f))
    if not trovate:
        return campo(None, "da_verificare", None,
                      "Nessuna data di scadenza nel testo: misura chiusa o a sportello continuo, da verificare"), None
    ultima, cit, _, _ = max(trovate, key=lambda x: x[0])
    if cit not in testo:
        return campo(ultima.isoformat(), "da_verificare", None, "Citazione non trovata nel testo"), ultima
    distinte = {x[0] for x in trovate}
    intervallo = len(distinte) == 2 and all(x[2] for x in trovate) and len({x[3] for x in trovate}) == 1
    if len(distinte) == 1 or intervallo:
        return campo(ultima.isoformat(), "confermato", cit), ultima
    return campo(ultima.isoformat(), "da_verificare", cit, "Più date nel testo: verificare quale vale"), ultima


def leggi_lista(url):
    trovate, errori, visitate = {}, [], set()
    coda, provato_semplice = [url + "?limit=100"], False
    while coda and len(visitate) < MAX_PAGINE_LISTA:
        u = coda.pop(0)
        if u in visitate:
            continue
        visitate.add(u)
        try:
            html = scarica(u)
        except requests.RequestException as e:
            if u.endswith("?limit=100") and not provato_semplice:
                provato_semplice = True
                coda.insert(0, url)
            else:
                errori.append(f"MIMIT: pagina elenco non letta ({type(e).__name__}): {u}")
            continue
        for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
            full = urljoin(u, a["href"]).split("#")[0]
            p = urlparse(full)
            if p.netloc and p.netloc != urlparse(BASE).netloc:
                continue
            parti = [x for x in p.path.split("/") if x]
            if len(parti) == 3 and parti[:2] == ["it", "incentivi"]:
                url_s = BASE + p.path
                t = pulisci(a.get_text())
                if url_s not in trovate or (t and not trovate[url_s]):
                    trovate[url_s] = t
            elif p.path.startswith("/it/incentivi-mise") and ("start=" in p.query or "page=" in p.query):
                coda.append(full)
    return trovate, len(visitate), errori


def main():
    oggi = dt.date.today()
    errori, schede, pagine = [], {}, 0
    for lista in LISTE:
        t, n, err = leggi_lista(lista)
        schede.update({k: v for k, v in t.items() if k not in schede or (v and not schede[k])})
        pagine += n
        errori += err
    if not schede:
        raise SystemExit("MIMIT: nessuna scheda trovata negli elenchi: la struttura della pagina potrebbe essere cambiata. "
                         + "; ".join(errori))
    scartati = {"non_ricerca": 0, "scaduto": 0, "chiuso": 0, "non_letta": 0, "oltre_limite": 0}
    bandi = []
    for i, (url, titolo_lista) in enumerate(schede.items()):
        if i >= MAX_SCHEDE:
            scartati["oltre_limite"] += 1
            continue
        try:
            time.sleep(0.5)
            html = scarica(url)
        except requests.RequestException:
            scartati["non_letta"] += 1
            continue
        h1 = BeautifulSoup(html, "html.parser").find("h1")
        titolo = pulisci(h1.get_text()) if h1 and pulisci(h1.get_text()) else titolo_lista
        testo = testo_pagina(html)
        if not RICERCA.search(testo):
            scartati["non_ricerca"] += 1
            continue
        scad, ultima = scadenza(testo)
        if ultima and ultima < oggi:
            scartati["scaduto"] += 1
            continue
        if ultima is None and CHIUSO.search(testo):
            scartati["chiuso"] += 1
            continue
        bandi.append({
            "canale": "Nazionale", "ente": "MIMIT", "titolo": titolo, "url": url, "data_lettura": oggi.isoformat(),
            "scadenza": scad,
            "durata": campo(None, "non_presente", None, "Non estratta"),
            "budget": campo(None, "non_presente", None, "Non estratto"),
            "ammissibilita": campo(None, "non_presente", None, "Il testo letto non indica i destinatari"),
            "testo_fonte": testo[:8000],
            "rilevanza": None,
        })
    with open("bandi_mimit.json", "w", encoding="utf-8") as f:
        json.dump({"generato": oggi.isoformat(), "errori": errori, "bandi": bandi}, f, ensure_ascii=False, indent=2)
    print(f"MIMIT: {len(schede)} schede trovate in {pagine} pagine di elenco; tenuti {len(bandi)}; scartati {scartati}; errori {len(errori)}")


if __name__ == "__main__":
    main()
