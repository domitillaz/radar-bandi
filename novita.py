"""Segna i bandi comparsi per la prima volta: scrive "prima_visto" (data) in ogni bando e tiene data/storico.json.

Come funziona
- storico.json associa a ogni bando (chiave = indirizzo, o canale+titolo se manca) la data in cui è stato visto la prima volta.
- Alla prima esecuzione tutti i bandi già presenti ricevono "iniziale": true e non vengono presentati come nuovi.
- Un bando che sparisce e ricompare (sito che non risponde una notte) mantiene la data originale: non risulta nuovo.
- Si lancia dopo i collettori e il filtro, nella cartella data:  python ../novita.py bandi*.json
Nessun dato viene dedotto: la data è quella dell'esecuzione in cui il bando è stato letto per la prima volta.
"""
import datetime as dt
import json
import os
import sys

STORICO = "storico.json"


def chiave(b):
    u = (b.get("url") or "").strip().lower().rstrip("/")
    return u if u and u != "#" else f"{b.get('canale', '')}|{(b.get('titolo') or '').strip().lower()}"


def main(files):
    oggi = dt.date.today().isoformat()
    primo_avvio = not os.path.exists(STORICO)
    st = {"creato": oggi, "visti": {}} if primo_avvio else json.load(open(STORICO, encoding="utf-8"))
    nuovi = 0
    for f in files:
        dati = json.load(open(f, encoding="utf-8"))
        for b in dati["bandi"]:
            k = chiave(b)
            if k not in st["visti"]:
                st["visti"][k] = oggi
                nuovi += 0 if primo_avvio else 1
            b["prima_visto"] = st["visti"][k]
            if st["visti"][k] <= st["creato"]:
                b["iniziale"] = True
            else:
                b.pop("iniziale", None)
        json.dump(dati, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(st, open(STORICO, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
    print(("Primo avvio: %d bandi registrati come già presenti" % len(st["visti"])) if primo_avvio
          else f"Novità di oggi: {nuovi} bandi mai visti prima (storico: {len(st['visti'])})")


if __name__ == "__main__":
    main(sys.argv[1:])
