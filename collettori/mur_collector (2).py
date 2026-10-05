"""Collettore MUR -> bandi_mur.json

Fonti:
  1. Ricerca Internazionale (ricercainternazionale.mur.gov.it): avvisi integrativi nazionali e bandi
     delle partnership europee (CHIPS, SBEP, PRIMA, Water4All, ...). Ogni notizia è un <h3> con link.
  2. Portale PRIN (prin.mur.gov.it): righe che iniziano con "Bando PRIN/FIS/Synergy".
Regole: nessuna data "confermata" senza una citazione trovata alla lettera nel testo; i bandi già
scaduti o vecchi e senza scadenza non vengono salvati.
ATTENZIONE: il codice HTML dei siti non è stato verificato; i selettori si basano sul testo delle pagine.
Un elenco vuoto è plausibile (le call PRIN/FIS sono annuali); un elenco vuoto perché la struttura è cambiata
viene invece dichiarato in "errori". Richiede: pip install requests beautifulsoup4
"""
import datetime as dt
import json
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

RI_URL = "http://www.ricercainternazionale.mur.gov.it/"
PRIN_URL = "https://prin.mur.gov.it/"
GIORNI_VECCHIO = 270
MESI = {m: i for i, m in enumerate(
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split(), 1)}
MESE_RE = "|".join(MESI)
TXT = re.compile(rf"(\d{{1,2}})\s*°?\s+({MESE_RE})\s+(\d{{4}})", re.I)
NUM = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
RIGA_DATA = re.compile(rf"^\s*(\d{{1,2}})\s+({MESE_RE})\s+(\d{{4}})\s*$", re.I)
PREANNUNCIO = re.compile(r"preannuncio|pre-?informazione", re.I)
SI_BANDO = re.compile(r"\b(bando|bandi|call|avviso|scadenza|proposal|proposte|domande)\b", re.I)
NO_TITOLO = re.compile(r"presa\s+d.atto|esito|graduatoria|webinar|consultazione|borse?\b|linee\s+guida|normativa", re.I)
NO_TESTO = re.compile(r"ammissione al finanziamento|presa\s+d.atto", re.I)


def pulisci(s):
    return " ".join(s.split())


def scarica(url):
    r = requests.get(url, timeout=30, headers={"User-Agent": "radar-bandi/0.1 (ricerca universitaria)"})
    r.raise_for_status()
    return r.text


def testo_pagina(html):
    """Testo del contenuto principale: toglie menu, intestazioni e piè di pagina."""
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        t.decompose()
    nodo = soup.find("main") or soup.find("article") or soup.body or soup
    return pulisci(nodo.get_text(" ", strip=True))


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


def scadenza(titolo, testo):
    if PREANNUNCIO.search(titolo):
        return campo(None, "da_verificare", None, "Preannuncio: la data nel testo è di pubblicazione, non di scadenza")
    d = date_nel_testo(testo)
    if not d:
        return campo(None, "non_presente", None, "Nessuna data nel testo")
    s, e, ultima = d[-1]
    cit = testo[max(0, s - 40):e]
    if len(d) == 1:
        return campo(ultima.isoformat(), "confermato", cit)
    if len(d) == 2:  # intervallo "dal ... al ..."
        prima = testo[max(0, d[0][0] - 25):d[0][0]].lower()
        tra = testo[d[0][1]:d[1][0]].lower()[-25:]
        if re.search(r"\b(dal|dalle|da)\b", prima) and re.search(r"\b(al|alle|fino al|entro il)\b", tra):
            return campo(ultima.isoformat(), "confermato", testo[max(0, d[0][0] - 25):e])
    return campo(ultima.isoformat(), "da_verificare", cit, "Più date nel testo: verificare quale è la chiusura")


def verifica(c, testo):
    if c["stato"] == "confermato" and (not c["citazione"] or c["citazione"] not in testo):
        return campo(c["valore"], "da_verificare", None, "Citazione non trovata nel testo")
    return c


def blocchi_ri(html):
    """Ogni notizia è un <h3> con link; la data precede il titolo, la descrizione lo segue."""
    soup = BeautifulSoup(html, "html.parser")
    for h in soup.find_all("h3"):
        a = h.find("a", href=True)
        if not a:
            continue
        pezzi = []
        for el in h.next_elements:
            if isinstance(el, Tag) and el.name == "h3":
                break
            if isinstance(el, NavigableString) and pulisci(str(el)) and el.parent not in h.descendants:
                pezzi.append(pulisci(str(el)))
        pezzi = [p for p in pezzi if not RIGA_DATA.match(p)]
        if len(pezzi) > 1 and len(pezzi[-1]) < 50:  # etichetta di categoria della notizia successiva
            pezzi = pezzi[:-1]
        prec = h.find_previous(string=RIGA_DATA)
        pub = None
        if prec:
            m = RIGA_DATA.match(prec)
            pub = data(int(m.group(3)), MESI[m.group(2).lower()], int(m.group(1)))
        yield pulisci(a.get_text()), " ".join(pezzi)[:900], urljoin(RI_URL, a["href"]), pub


def blocchi_prin(html):
    righe = [pulisci(x) for x in BeautifulSoup(html, "html.parser").get_text("\n").split("\n") if pulisci(x)]
    for i, r in enumerate(righe):
        if re.match(r"^bando\s+(prin|fis|synergy)", r, re.I):
            resto = []
            for x in righe[i + 1:i + 5]:
                if re.match(r"^bando\s", x, re.I):
                    break
                resto.append(x)
            yield r, " ".join(resto), PRIN_URL, None


def main():
    oggi = dt.date.today()
    bandi, errori, visti = [], [], set()
    scartati = {"non_bando": 0, "scaduto": 0, "vecchio": 0}
    for nome, url, fn in [("ricercainternazionale", RI_URL, blocchi_ri), ("prin", PRIN_URL, blocchi_prin)]:
        try:
            blocchi = list(fn(scarica(url)))
        except requests.RequestException as e:
            errori.append(f"MUR: fonte '{nome}' non raggiungibile ({type(e).__name__})")
            continue
        if not blocchi:
            errori.append(f"MUR: nessun blocco riconosciuto in '{nome}': la struttura della pagina potrebbe essere cambiata")
            continue
        for titolo, resto, link, pub in blocchi:
            if titolo in visti:
                continue
            if nome == "ricercainternazionale" and (not SI_BANDO.search(titolo + " " + resto)
                                                    or NO_TITOLO.search(titolo) or NO_TESTO.search(resto)):
                scartati["non_bando"] += 1
                continue
            visti.add(titolo)
            scheda = ""
            scad = verifica(scadenza(titolo, resto), resto)
            v = scad["valore"]
            if v and dt.date.fromisoformat(v) < oggi:
                scartati["scaduto"] += 1
                continue
            if link != url:  # il testo della scheda serve a scadenza, rilevanza e destinatari
                try:
                    time.sleep(1)
                    scheda = testo_pagina(scarica(link))
                    if scad["stato"] == "non_presente" and not PREANNUNCIO.search(titolo):
                        scad = verifica(scadenza(titolo, scheda), scheda)
                except requests.RequestException:
                    pass
            v = scad["valore"]
            if v and dt.date.fromisoformat(v) < oggi:
                scartati["scaduto"] += 1
                continue
            if not v and pub and (oggi - pub).days > GIORNI_VECCHIO:
                scartati["vecchio"] += 1
                continue
            bandi.append({
                "canale": "Nazionale", "ente": "MUR", "titolo": titolo, "url": link,
                "data_lettura": oggi.isoformat(), "data_pubblicazione": pub.isoformat() if pub else None,
                "scadenza": scad,
                "durata": campo(None, "non_presente", None, "Non estratta"),
                "budget": campo(None, "non_presente", None, "Non estratto"),
                "ammissibilita": campo(None, "non_presente", None, "Il testo letto non indica i destinatari"),
                "testo_fonte": (scheda or resto)[:8000],
                "rilevanza": None,
            })
    if len(errori) == 2:
        raise SystemExit("Entrambe le fonti MUR sono fallite: " + "; ".join(errori))
    with open("bandi_mur.json", "w", encoding="utf-8") as f:
        json.dump({"generato": oggi.isoformat(), "errori": errori, "bandi": bandi}, f, ensure_ascii=False, indent=2)
    print(f"{len(bandi)} bandi MUR scritti; scartati: {scartati}; errori: {len(errori)}")


if __name__ == "__main__":
    main()
