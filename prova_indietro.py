"""Prova all'indietro sul portale europeo: il radar avrebbe trovato i bandi già vinti dal gruppo?

Si lancia da GitHub (Actions -> "Prova all'indietro" -> Run workflow): la rete dell'ambiente di sviluppo
non raggiunge il portale. Stampa tre cose nel log:
  1. se il topic esiste ancora nel portale e che punteggio avrebbe oggi (titolo + testo restituito dalla ricerca);
  2. con quali parole chiave di ricerca il topic sarebbe stato trovato (tra i topic chiusi);
  3. il rumore: quanti topic chiusi trovati dalle stesse parole chiave prenderebbero un punteggio >= soglia.
Aggiungi altri identificativi di bandi vinti in gold_europa.txt (uno per riga, # per i commenti).
ATTENZIONE: i nomi dei campi dell'API non sono documentati ufficialmente.
"""
import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "collettori"))
import fundingtenders_collector as F  # noqa: E402
import filtro_parole_chiave as K  # noqa: E402

GOLD = ["HORIZON-MISS-2023-CANCER-01-01"]  # ARTURO (verificato su CORDIS)
STATI_TUTTI = ["31094501", "31094502", "31094503"]
STATO_CHIUSO = ["31094503"]
SOGLIA = 6


def cerca(testo, stati, pagina=1):
    query = {"bool": {"must": [{"terms": {"type": ["1"]}}, {"terms": {"status": stati}}]}}
    r = requests.post(
        F.API, params={"apiKey": "SEDIA", "text": testo, "pageSize": 50, "pageNumber": pagina},
        files={"query": (None, json.dumps(query), "application/json"),
               "languages": (None, json.dumps(["en"]), "application/json")},
        headers={"User-Agent": "radar-bandi/0.1 (ricerca universitaria)"}, timeout=60)
    r.raise_for_status()
    return r.json().get("results") or []


def ident(r):
    return str((F.meta(r, "identifier") or [r.get("reference") or ""])[0])


def titolo(r):
    return str((F.meta(r, "title") or [r.get("title") or ""])[0])


def valuta(r):
    b = {"titolo": f"{ident(r)}: {titolo(r)}", "testo_fonte": F.testo_topic(r)}
    return K.valuta(b), len(b["testo_fonte"])


def leggi_gold():
    g = list(GOLD)
    if os.path.exists("gold_europa.txt"):
        for riga in open("gold_europa.txt", encoding="utf-8"):
            riga = riga.split("#")[0].strip()
            if riga and riga not in g:
                g.append(riga)
    return g


def main():
    gold = leggi_gold()
    print("== 1. Il topic esiste nel portale e che punteggio avrebbe?")
    for g in gold:
        try:
            trovato = next((r for r in cerca(g, STATI_TUTTI) if ident(r).lower() == g.lower()), None)
        except (requests.RequestException, ValueError) as e:
            print(f"{g}: ricerca non riuscita ({type(e).__name__})")
            continue
        if not trovato:
            print(f"{g}: NON trovato nel portale cercando per identificativo (potrebbe essere stato rimosso)")
            continue
        p, n = valuta(trovato)
        print(f"{g}: titolo '{titolo(trovato)[:100]}' | testo letto {n} caratteri | punteggio {p['punteggio']} "
              f"({p['stato']}) temi {p['temi']}")
    print("== 2. Con quali parole chiave di ricerca sarebbe stato trovato (tra i topic chiusi)?")
    chiusi, per_parola = {}, {}
    for parola in F.PAROLE:
        ids = set()
        for pag in (1, 2):
            try:
                res = cerca(parola, STATO_CHIUSO, pag)
            except (requests.RequestException, ValueError) as e:
                print(f"  ricerca '{parola}' pagina {pag} non riuscita ({type(e).__name__})")
                break
            for r in res:
                ids.add(ident(r).lower())
                chiusi.setdefault(ident(r).lower(), r)
            time.sleep(1)
        per_parola[parola] = ids
    for g in gold:
        qs = [p for p, ids in per_parola.items() if g.lower() in ids]
        print(f"{g}: trovato da {qs if qs else 'NESSUNA parola chiave (il radar non lo avrebbe visto)'}")
    print("== 3. Rumore: topic chiusi trovati dalle stesse parole chiave")
    punteggi = {i: valuta(r)[0] for i, r in chiusi.items()}
    alti = [(p["punteggio"], i) for i, p in punteggi.items() if (p["punteggio"] or 0) >= SOGLIA]
    nv = sum(1 for p in punteggi.values() if p["punteggio"] is None)
    print(f"topic chiusi trovati {len(chiusi)}; con punteggio >= {SOGLIA}: {len(alti)}; non valutabili: {nv}")
    for s, i in sorted(alti, reverse=True)[:12]:
        print(f"  {s}/10 {i}: {titolo(chiusi[i])[:80]}")


if __name__ == "__main__":
    main()
