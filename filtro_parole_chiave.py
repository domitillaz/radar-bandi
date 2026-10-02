"""Filtro a parole chiave: alternativa GRATUITA all'agente di rilevanza (nessuna chiave API).

Cosa fa e cosa NON fa:
- Cerca nel titolo e nel testo della fonte termini legati ai temi del gruppo.
- Termini FORTI (lab-on-chip, organ-on-chip, microfluidic, biosensor, point-of-care, machine learning
  con contesto sanitario): il punteggio è 4 + 2 per ogni tema forte + 1 se c'è anche un tema debole
  + 1 se compare nel titolo (max 10).
- Termini DEBOLI (sensori generici, dispositivi medici, diagnostica in vitro): possono comparire di passaggio
  in qualsiasi bando di sanità. Da soli il punteggio resta sotto la soglia: massimo 5.
- È una corrispondenza lessicale, non un giudizio sul contenuto. Nella dashboard è etichettata "parole chiave".
- Le evidenze sono frammenti copiati dal testo, dove è comparso il termine.
- Se non trova nulla e il testo è troppo corto per escludere la pertinenza, il bando resta "da_verificare".
- Non stabilisce a chi è rivolto il bando (destinatari: sempre "non_indicato").
Uso: python filtro_parole_chiave.py bandi.json bandi_europa.json
"""
import argparse
import json
import re

VERSIONE = "parole-chiave-2"
MIN_CARATTERI = 300
SALUTE = re.compile(r"\b(health\w*|medic\w*|clinic\w*|biomedic\w*|patients?|diagnos\w*|therap\w*|salute|sanit[aà]|pazient\w*)\b", re.I)

# (espressione, richiede un termine di salute nel testo, debole). In ogni tema le regole forti vengono prima.
TEMI = {
    "ml_dati_biomedici": [(r"\bmachine[\s-]*learning\b|\bdeep[\s-]*learning\b|\bartificial[\s-]*intelligence\b|\bintelligenza[\s-]*artificiale\b|\bapprendimento[\s-]*automatico\b|\bneural[\s-]*networks?\b|\breti[\s-]*neurali\b", True, False)],
    "sensoristica": [(r"\bbiosensor\w*|\bwearables?\b", False, False),
                     (r"\bsensoristica\b|\bsensors?\b|\bsensori\b", True, True)],
    "lab_on_chip": [(r"\blab[\s-]*on[\s-]*(?:a[\s-]*)?chip\b|\bpoint[\s-]*of[\s-]*care\b", False, False)],
    "organ_on_chip": [(r"\borgans?[\s-]*on[\s-]*(?:a[\s-]*)?chips?\b|\bmicrophysiological\b|\borganoid\w*", False, False)],
    "microfluidica": [(r"\bmicro[\s-]*fluidic\w*|\bmicrofluidica\b", False, False)],
    "tecnologie_emergenti_biomedicali": [(r"\bmedical[\s-]*devices?\b|\bdispositiv\w*[\s-]*medic\w*|\bin[\s-]*vitro[\s-]*diagnostic\w*|\bdiagnostica[\s-]*in[\s-]*vitro\b|\bmedtech\b", False, True)],
}


def da_verificare(motivo):
    return {"punteggio": None, "stato": "da_verificare", "motivazione": motivo,
            "temi": [], "evidenze": [], "destinatari": None}


def valuta(bando):
    titolo = " ".join(bando.get("titolo", "").split())
    fonte = " ".join((bando.get("testo_fonte") or "").split())
    testo = titolo + ". " + fonte
    salute = bool(SALUTE.search(testo))
    forti, deboli, evidenze, nel_titolo = [], [], [], False
    for tema, regole in TEMI.items():
        for pat, serve_salute, debole in regole:
            if serve_salute and not salute:
                continue
            m = re.search(pat, testo, re.I)
            if m:
                (deboli if debole else forti).append(tema)
                evidenze.append(testo[max(0, m.start() - 60): m.end() + 60])
                nel_titolo = nel_titolo or bool(re.search(pat, titolo, re.I))
                break
    evidenze = [e for e in evidenze if e in testo][:3]  # ogni evidenza è un frammento reale del testo
    temi = forti + deboli
    if forti:
        p = min(10, 4 + 2 * len(forti) + (1 if deboli else 0) + (1 if nel_titolo else 0))
        mot = "Trovati termini dei temi: " + ", ".join(temi) + ". Corrispondenza lessicale, non un giudizio sul contenuto."
    elif deboli:
        p = min(5, 3 + len(deboli))
        mot = ("Solo termini generici (" + ", ".join(deboli) + "), che possono comparire di passaggio: "
               "corrispondenza debole, punteggio limitato a 5.")
    elif len(fonte) < MIN_CARATTERI:
        return da_verificare("Nessun termine trovato, ma il testo è troppo corto per escludere la pertinenza")
    else:
        p, mot = 0, "Nessun termine dei temi nel testo."
    return {"punteggio": p, "stato": "parole_chiave", "motivazione": mot, "temi": temi, "evidenze": evidenze,
            "destinatari": {"valore": "non_indicato", "citazione": None}, "rubrica": VERSIONE}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    for f in ap.parse_args().files:
        dati = json.load(open(f, encoding="utf-8"))
        for b in dati["bandi"]:
            b["rilevanza"] = valuta(b)
        json.dump(dati, open(f, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"{f}: {len(dati['bandi'])} bandi valutati per parole chiave")


if __name__ == "__main__":
    main()
