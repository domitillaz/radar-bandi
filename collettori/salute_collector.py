"""Collettore Salute (Regione Lazio, sezione Salute) -> bandi_salute.json

Perché esiste: alcuni finanziamenti alla ricerca biomedica (ad esempio gli avvisi PNRR M6C2 del Ministero della
Salute, gestiti dalle Regioni) non compaiono né su Lazio Innova né sul MIMIT, ma sulle pagine "Salute" del sito
della Regione. Di solito i proponenti sono Aziende sanitarie / ospedaliero-universitarie e l'università partecipa
come partner: la colonna "Università ammessa?" lo dirà solo se la pagina lo scrive.

Come funziona (stesse regole degli altri collettori, riuso delle funzioni del collettore MIMIT):
- legge gli elenchi di notizie/avvisi della sezione Salute, apre ogni pagina, tiene solo quelle che parlano di
  un avviso/bando E di ricerca o finanziamento per la sanità;
- la scadenza è letta solo dalle frasi che parlano di scadenza ("entro il", "dal ... al"), con citazione letterale;
  più date diverse o nessuna data = "da_verificare"; tutte le date già passate = bando scartato;
- il testo completo va al filtro di rilevanza.
LIMITI NOTI: il codice HTML del sito non è stato verificato (dal mio ambiente il sito non è raggiungibile con
la shell). Il sito del Ministero della Salute (salute.gov.it) è protetto da una verifica del browser e non è
leggibile da uno script: non è incluso. Se la struttura cambia il collettore lo dichiara negli errori.
Richiede: pip install requests beautifulsoup4
"""
import datetime as dt
import json
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import mimit_collector as M  # stessa cartella: funzioni comuni (scadenza, testo_pagina, campo, pulisci)

BASE = "https://regione.lazio.it"
LISTE = [BASE + "/notizie/salute", BASE + "/enti/salute"]
SEZIONI = ("notizie/salute", "enti/salute", "imprese/salute", "cittadini/salute")
MAX_PAGINE_LISTA = 10
MAX_SCHEDE = 120
BANDO = re.compile(r"\bavvis\w+|\bbando\b|\bbandi\b|manifestazion\w+\s+di\s+interesse|\bcall\b|finanziament\w+", re.I)
RICERCA_SALUTE = re.compile(r"ricerca\s+(?:biomedica|sanitaria|scientifica|clinica|traslazionale|finalizzata)"
                            r"|progetti?\s+di\s+ricerca|\bPNRR\b|M6C2|malattie\s+(?:rare|croniche)|innovazione\s+sanitaria"
                            r"|sperimentazion\w+|dispositiv\w+\s+medic\w+|\bdigital\w+\s+(?:health|sanit\w+)", re.I)
CHIUSO = M.CHIUSO


def leggi_lista(url):
    trovate, errori, visitate = {}, [], set()
    coda = [url]
    while coda and len(visitate) < MAX_PAGINE_LISTA:
        u = coda.pop(0)
        if u in visitate:
            continue
        visitate.add(u)
        try:
            html = M.scarica(u)
        except requests.RequestException as e:
            errori.append(f"Salute: pagina elenco non letta ({type(e).__name__}): {u}")
            continue
        for a in BeautifulSoup(html, "html.parser").find_all("a", href=True):
            full = urljoin(u, a["href"]).split("#")[0]
            p = urlparse(full)
            if p.netloc and p.netloc != urlparse(BASE).netloc:
                continue
            path = p.path.rstrip("/")
            parti = [x for x in path.split("/") if x]
            sezione = "/".join(parti[:2])
            if sezione in SEZIONI and p.query and re.search(r"(?:^|&)(?:page|pagina|start|p)=", p.query):
                coda.append(full)
            elif sezione in SEZIONI and len(parti) >= 3 and not path.endswith("index.php"):
                url_s = BASE + path
                t = M.pulisci(a.get_text())
                if url_s not in trovate or (t and not trovate[url_s]):
                    trovate[url_s] = t
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
        raise SystemExit("Salute: nessuna pagina trovata negli elenchi: la struttura potrebbe essere cambiata. "
                         + "; ".join(errori))
    scartati = {"non_bando": 0, "scaduto": 0, "chiuso": 0, "non_letta": 0, "oltre_limite": 0}
    bandi = []
    for i, (url, titolo_lista) in enumerate(schede.items()):
        if i >= MAX_SCHEDE:
            scartati["oltre_limite"] += 1
            continue
        try:
            time.sleep(0.5)
            html = M.scarica(url)
        except requests.RequestException:
            scartati["non_letta"] += 1
            continue
        h1 = BeautifulSoup(html, "html.parser").find("h1")
        titolo = M.pulisci(h1.get_text()) if h1 and M.pulisci(h1.get_text()) else titolo_lista
        testo = M.testo_pagina(html)
        if not (BANDO.search(titolo + " " + testo[:600]) and RICERCA_SALUTE.search(titolo + " " + testo)):
            scartati["non_bando"] += 1
            continue
        scad, ultima = M.scadenza(testo)
        if ultima and ultima < oggi:
            scartati["scaduto"] += 1
            continue
        if ultima is None and CHIUSO.search(testo):
            scartati["chiuso"] += 1
            continue
        bandi.append({
            "canale": "Regionale", "ente": "Regione Lazio (Salute)", "titolo": titolo, "url": url,
            "data_lettura": oggi.isoformat(), "scadenza": scad,
            "durata": M.campo(None, "non_presente", None, "Non estratta"),
            "budget": M.campo(None, "non_presente", None, "Non estratto"),
            "ammissibilita": M.campo(None, "non_presente", None, "Il testo letto non indica i destinatari"),
            "testo_fonte": testo[:8000],
            "rilevanza": None,
        })
    with open("bandi_salute.json", "w", encoding="utf-8") as f:
        json.dump({"generato": oggi.isoformat(), "errori": errori, "bandi": bandi}, f, ensure_ascii=False, indent=2)
    print(f"SALUTE: {len(schede)} pagine trovate in {pagine} pagine di elenco; tenuti {len(bandi)}; "
          f"scartati {scartati}; errori {len(errori)}")


if __name__ == "__main__":
    main()
