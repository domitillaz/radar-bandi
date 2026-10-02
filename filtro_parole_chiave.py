"""Filtro a parole chiave: alternativa GRATUITA all'agente di rilevanza (nessuna chiave API).

Cosa fa e cosa NON fa:
- Cerca nel titolo e nel testo della fonte termini legati ai temi del gruppo.
- Il punteggio è una regola fissa (4 + 2 per ogni tema trovato + 1 se compare nel titolo, max 10):
  è una corrispondenza lessicale, non un giudizio sul contenuto. Nella dashboard è etichettata "parole chiave".
- Le evidenze sono frammenti copiati dal testo, dove è comparso il termine.
- Se non trova nulla e il testo è troppo corto per escludere la pertinenza, il bando resta "da_verificare":
  l'assenza di parole chiave in poche righe non significa che il bando sia irrilevante.
- Non stabilisce a chi è rivolto il bando (destinatari: sempre "non_indicato").
Uso: python filtro_parole_chiave.py bandi.json bandi_europa.json
"""
import argparse
import json
import re

VERSIONE = "parole-chiave-1"
MIN_CARATTERI = 300
SALUTE = re.compile(r"\b(health\w*|medic\w*|clinic\w*|biomedic\w*|patients?|diagnos\w*|therap\w*|salute|sanit[aà]|pazient\w*)\b", re.I)

# (espressione, richiede un termine di salute nello stesso testo)
TEMI = {
    "ml_dati_biomedici": [(r"\bmachine[\s-]*learning\b|\bdeep[\s-]*learning\b|\bartificial[\s-]*intelligence\b|\bintelligenza[\s-]*artificiale\b|\bapprendimento[\s-]*automatico\b|\bneural[\s-]*networks?\b|\breti[\s-]*neurali\b", True)],
    "sensoristica": [(r"\bbiosensor\w*|\bwearables?\b", False), (r"\bsensoristica\b|\bsensors?\b|\bsensori\b", True)],
    "lab_on_chip": [(r"\blab[\s-]*on[\s-]*(?:a[\s-]*)?chip\b|\bpoint[\s-]*of[\s-]*care\b", False)],
    "organ_on_chip": [(r"\borgans?[\s-]*on[\s-]*(?:a[\s-]*)?chips?\b|\bmicrophysiological\b|\borganoid\w*", False)],
    "microfluidica": [(r"\bmicro[\s-]*fluidic\w*|\bmicrofluidica\b", False)],
    "tecnologie_emergenti_biomedicali": [(r"\bmedical[\s-]*devices?\b|\bdispositiv\w*[\s-]*medic\w*|\bin[\s-]*vitro[\s-]*diagnostic\w*|\bdiagnostica[\s-]*in[\s-]*vitro\b|\bmedtech\b", False)],
}


def da_verificare(motivo):
    return {"punteggio": None, "stato": "da_verificare", "motivazione": motivo,
            "temi": [], "evidenze": [], "destinatari": None}


def valuta(bando):
    titolo = " ".join(bando.get("titolo", "").split())
    fonte = " ".join((bando.get("testo_fonte") or "").split())
    testo = titolo + ". " + fonte
    salute = bool(SALUTE.search(testo))
    temi, evidenze, nel_titolo = [], [], False
    for tema, regole in TEMI.items():
        for pat, serve_salute in regole:
            if serve_salute and not salute:
                continue
            m = re.search(pat, testo, re.I)
            if m:
                temi.append(tema)
                evidenze.append(testo[max(0, m.start() - 60): m.end() + 60])
                nel_titolo = nel_titolo or bool(re.search(pat, titolo, re.I))
                break
    evidenze = [e for e in evidenze if e in testo][:3]  # ogni evidenza è un frammento reale del testo
    if temi:
        p = min(10, 4 + 2 * len(temi) + (1 if nel_titolo else 0))
        return {"punteggio": p, "stato": "parole_chiave",
                "motivazione": "Trovati termini dei temi: " + ", ".join(temi) + ". Corrispondenza lessicale, non un giudizio sul contenuto.",
                "temi": temi, "evidenze": evidenze,
                "destinatari": {"valore": "non_indicato", "citazione": None}, "rubrica": VERSIONE}
    if len(fonte) < MIN_CARATTERI:
        return da_verificare("Nessun termine trovato, ma il testo è troppo corto per escludere la pertinenza")
    return {"punteggio": 0, "stato": "parole_chiave", "motivazione": "Nessun termine dei temi nel testo.",
            "temi": [], "evidenze": [], "destinatari": {"valore": "non_indicato", "citazione": None}, "rubrica": VERSIONE}


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
