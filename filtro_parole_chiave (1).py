"""Filtro a parole chiave: alternativa GRATUITA all'agente di rilevanza (nessuna chiave API).

Cosa fa e cosa NON fa:
- Cerca nel titolo e nel testo della fonte termini legati ai temi del gruppo.
- Termini FORTI (lab-on-chip, organ-on-chip, microfluidic, biosensor, point-of-care, machine learning
  con contesto sanitario): il punteggio è 4 + 2 per ogni tema forte + 1 se c'è anche un tema debole
  + 1 se compare nel titolo (max 10).
- Per i termini che hanno senso solo in ambito sanitario (machine learning, sensori generici) deve comparire un
  termine di salute entro 200 caratteri dalla menzione, non in un punto qualsiasi del testo; e una menzione
  isolata in un testo lungo (non nel titolo) conta come debole.
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

VERSIONE = "parole-chiave-9"
PROGRAMMI_NOTI = re.compile(r"HORIZON-MISS-\d{4}-CANCER", re.I)  # Missione Cancro: programma di ARTURO (verificato su CORDIS)
PROMUOVI_IN_TITOLO = {"sensoristica", "tecnologie_emergenti_biomedicali"}  # un termine debole nel titolo vale come forte
GENERICO = re.compile(r"ricerca industriale|sviluppo sperimentale|organismi di ricerca|progetti di ricerca e sviluppo", re.I)
VICINANZA = 200  # caratteri entro cui deve comparire un termine di salute
MIN_CARATTERI = 300
SALUTE = re.compile(r"\b(health\w*|medic\w*|clinic\w*|biomedic\w*|patients?|diagnos\w*|therap\w*|salute|sanit[aà]|pazient\w*)\b", re.I)

# (espressione, richiede un termine di salute nel testo, debole). In ogni tema le regole forti vengono prima.
TEMI = {
    "ml_dati_biomedici": [(r"\bmachine[\s-]*learning\b|\bdeep[\s-]*learning\b|\bartificial[\s-]*intelligence\b|\bintelligenza[\s-]*artificiale\b|\bapprendimento[\s-]*automatico\b|\bneural[\s-]*networks?\b|\breti[\s-]*neurali\b", True, False)],
    "sensoristica": [(r"\bbiosensor\w*|\bwearables?\b", False, False),
                     (r"\bsensoristica\b|\bsensors?\b|\bsensori\b", True, True)],
    "lab_on_chip": [(r"\blab[\s-]*on[\s-]*(?:a[\s-]*)?chip\b|\bpoint[\s-]*of[\s-]*care\b", False, False)],
    "organ_on_chip": [(r"\borgans?[\s-]*on[\s-]*(?:a[\s-]*)?chips?\b|\b(?:tumou?rs?|cancer|disease|gut|lung|liver|heart|brain|kidney|body|human)[\s-]*on[\s-]*(?:a[\s-]*)?chips?\b|\bmicrophysiological\b|\borganoid\w*", False, False)],
    "microfluidica": [(r"\bmicro[\s-]*fluidic\w*|\bmicrofluidica\b", False, False)],
    "elettrodi_mea_grafene": [(r"\blaser[\s-]*induced[\s-]*graphene\b|\bgraphene[\s-]*(?:based[\s-]*)?(?:electrodes?|sensors?)\b|\bgrafene[\s-]*indotto\b|\belettrodi[\s-]*(?:in[\s-]*)?grafene\b|\bmulti[\s-]*electrode[\s-]*arrays?\b|\bmicro[\s-]*electrode[\s-]*arrays?\b|\barray[\s-]*di[\s-]*microelettrodi\b|\bbio[\s-]*electronics?\b|\bbio[\s-]*elettronica\b", False, False)],
    "biologia_computazionale": [(r"\bcomputational[\s-]*biology\b|\bbiologia[\s-]*computazionale\b|\bmulti[\s-]*omics?\b|\bbio[\s-]*informatics?\b|\bbioinformatica\b|\bprecision[\s-]*(?:medicine|oncology)\b|\bpersonali[sz]ed[\s-]*(?:medicine|therap\w+)\b|\bmedicina[\s-]*(?:personalizzata|di[\s-]*precisione)\b", False, False)],
    "oncologia_immunoterapia": [(r"\bimmuno[\s-]*(?:therap\w+|oncology)\b|\bimmunoterapi\w+|\bcolorectal\b|\bcolon[\s-]*retto\b|\bcancer\b|\boncolog\w+|\bmicrobio(?:ta|me)\b|\btumou?rs?\b|\btumor[ei]\b", False, True)],
    "tossicita_farmaci": [(r"\bcardio[\s-]*tox\w*|\bcardiotossic\w*|\bdrug[\s-]*induced[\s-]*(?:toxicity|injury|tossicit\w+)|\bnew[\s-]*approach[\s-]*methodolog\w*|\bin[\s-]*vitro[\s-]*toxic\w*|\btossicologia[\s-]*in[\s-]*vitro\b", False, False),
                          (r"\bcytotox\w*|\bcitotossic\w*|\bbioactive\b|\bbioattiv\w*|\bnatural[\s-]*compounds?\b", False, True)],
    "algoritmi_bioispirati": [(r"\b(?:bio|nature)[\s-]*inspired[\s-]*(?:algorithms?|optimi[sz]ation|computing)\b|\balgoritmi[\s-]*(?:bio|natura)[\s-]*ispirati\b", False, False)],
    "tecnologie_emergenti_biomedicali": [(r"\bmedical[\s-]*devices?\b|\bdispositiv\w*[\s-]*medic\w*|\bin[\s-]*vitro[\s-]*diagnostic\w*|\bdiagnostica[\s-]*in[\s-]*vitro\b|\bmedtech\b", False, True)],
}


def da_verificare(motivo):
    return {"punteggio": None, "stato": "da_verificare", "motivazione": motivo,
            "temi": [], "evidenze": [], "destinatari": None}


def valuta(bando):
    titolo = " ".join((bando.get("titolo", "") + ". " + (bando.get("descrizione") or "")).split())
    fonte = " ".join((bando.get("testo_fonte") or "").split())
    testo = titolo + ". " + fonte
    forti, deboli, evidenze, nel_titolo = [], [], [], False
    for tema, regole in TEMI.items():
        for pat, serve_salute, debole in regole:
            ms = [m for m in re.finditer(pat, testo, re.I)
                  if not serve_salute or SALUTE.search(testo[max(0, m.start() - VICINANZA): m.end() + VICINANZA])]
            if not ms:
                continue
            m = ms[0]
            in_titolo = m.start() < len(titolo)
            isolata = serve_salute and len(ms) < 2 and not in_titolo and len(fonte) >= 600
            deb = (debole and not (in_titolo and tema in PROMUOVI_IN_TITOLO)) or isolata
            (deboli if deb else forti).append(tema)
            evidenze.append(testo[max(0, m.start() - 60): m.end() + 60])
            nel_titolo = nel_titolo or in_titolo
            break
    evidenze = [e for e in evidenze if e in testo][:3]  # ogni evidenza è un frammento reale del testo
    temi = forti + deboli
    if forti:
        p = min(10, 4 + 2 * len(forti) + (1 if deboli else 0) + (1 if nel_titolo else 0))
        mot = "Trovati termini dei temi: " + ", ".join(temi) + ". Corrispondenza lessicale, non un giudizio sul contenuto."
    elif deboli:
        p = min(5, 3 + len(deboli))
        mot = ("Solo termini generici o menzioni isolate (" + ", ".join(deboli) + "), che possono comparire di passaggio: "
               "corrispondenza debole, punteggio limitato a 5.")
    elif bando.get("ente") == "MIMIT" and GENERICO.search(testo):
        g = GENERICO.search(testo)
        p, temi = 6, ["ricerca_industriale_generica"]
        evidenze = [testo[max(0, g.start() - 60): g.end() + 60]]
        mot = ("Misura di ricerca e sviluppo per imprese, tema non specifico: l'università può essere partner di ricerca. "
               "Punteggio fisso, da valutare a mano.")
    elif len(fonte) < MIN_CARATTERI:
        return da_verificare("Nessun termine trovato, ma il testo è troppo corto per escludere la pertinenza")
    else:
        p, mot = 0, "Nessun termine dei temi nel testo."
    stato = "parole_chiave"
    if PROGRAMMI_NOTI.search(bando.get("titolo", "")) and p < 6:
        p, stato = 6, "programma_noto"
        mot = ("Topic della Missione Cancro, stesso programma di un progetto già finanziato al gruppo (ARTURO). "
               "Pertinenza da valutare a mano.")
    return {"punteggio": p, "stato": stato, "motivazione": mot, "temi": temi, "evidenze": evidenze,
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
