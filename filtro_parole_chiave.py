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

VERSIONE = "parole-chiave-20"
PROGRAMMI_NOTI = re.compile(r"HORIZON-MISS-\d{4}-CANCER", re.I)  # Missione Cancro: programma di ARTURO (verificato su CORDIS)
PROMUOVI_IN_TITOLO = {"sensoristica", "tecnologie_emergenti_biomedicali"}  # un termine debole nel titolo vale come forte
SANITA_RICERCA = re.compile(r"ricerca\s+(?:biomedica|sanitaria)|malattie\s+(?:croniche|rare)|progetti\s+di\s+ricerca\s+sanitaria", re.I)
SSH = re.compile(r"\bdemocra\w+|\bequality\b|\binclusive[\s-]*societ\w+|\bsocial[\s-]*sciences?\b|\bhumanities\b|\bcyberviolence\b|\bdisinformation\b", re.I)
ISOLABILI = {"ia_ricerca", "imaging"}  # temi senza vincolo di salute: una sola menzione in un testo lungo conta come debole
NUOVI = {"neuro_segnali", "ia_ricerca", "imaging", "digitale_dati", "analisi_dati"}
RICERCA_HINT = re.compile(r"universit\w+|organismi?\s+di\s+ricerca|enti\s+di\s+ricerca|ricerca\s+industriale|ricerca\s+e\s+sviluppo|research|\bgrants?\b|\bERC\b|\bMSCA\b", re.I)
GENERICO = re.compile(r"ricerca industriale|sviluppo sperimentale|organismi di ricerca|progetti di ricerca e sviluppo", re.I)
VICINANZA = 200  # caratteri entro cui deve comparire un termine di salute
MIN_CARATTERI = 300
SALUTE = re.compile(r"\b(scienze\s+della\s+vita|life\s+sciences?|health\w*|medic\w*|clinic\w*|biomedic\w*|patients?|diagnos\w*|therap\w*|salute|sanit[aà]|pazient\w*)\b", re.I)

# (espressione, richiede un termine di salute nel testo, debole). In ogni tema le regole forti vengono prima.
TEMI = {
    "ml_dati_biomedici": [(r"\bmachine[\s-]*learning\b|\bdeep[\s-]*learning\b|\bartificial[\s-]*intelligence\b|\bintelligenza[\s-]*artificiale\b|\bapprendimento[\s-]*automatico\b|\bneural[\s-]*networks?\b|\breti[\s-]*neurali\b", True, False)],
    "ia_ricerca": [(r"\bmachine[\s-]*learning\b|\bdeep[\s-]*learning\b|\bartificial[\s-]*intelligence\b|\bintelligenza[\s-]*artificiale\b|\bneural[\s-]*networks?\b|\breti[\s-]*neurali\b|\bcomputer[\s-]*vision\b|\bvisione[\s-]*artificiale\b|\bfoundation[\s-]*models?\b|\bgenerative[\s-]*AI\b|\blarge[\s-]*language[\s-]*models?\b|\btrustworthy[\s-]*AI\b|\bexplainable[\s-]*AI\b|\bAI[\s-]*models?\b", False, False)],
    "imaging": [(r"\bimage[\s-]*(?:analysis|processing|reconstruction|segmentation)\b|\bimaging\b|\belaborazione[\s-]*(?:di[\s-]*)?immagini\b|\banalisi[\s-]*(?:di[\s-]*)?immagini\b|\bmicroscop\w+|\bremote[\s-]*sensing\b|\btelerilevamento\b", False, False)],
    "digitale_dati": [(r"\bdigital[\s-]*twins?\b|\bgemell\w+[\s-]*digital\w+|\bdata[\s-]*driven\b|\bsignal[\s-]*processing\b|\belaborazione[\s-]*(?:dei[\s-]*)?segnali\b|\bhigh[\s-]*performance[\s-]*computing\b|\bcalcolo[\s-]*ad[\s-]*alte[\s-]*prestazioni\b|\bHPC\b", False, True)],
    "analisi_dati": [(r"\bdata[\s-]*(?:analysis|analytics|science|mining)\b|\bbig[\s-]*data\b|\banalisi[\s-]*(?:dei[\s-]*)?dati\b|\bscienza[\s-]*dei[\s-]*dati\b|\bpredictive[\s-]*model\w*|\bmodelli[\s-]*predittiv\w+|\bstatistical[\s-]*model\w*|\bmodellistica\b|\bnumerical[\s-]*simulation\w*|\binternet[\s-]*of[\s-]*things\b|\bIoT\b|\bsmart[\s-]*sensors?\b", False, True)],
    "neuro_segnali": [(r"\bEEG\b|\belectroencephalograph\w+|\belettroencefalograf\w+|\beye[\s-]*tracking\b|\bneuro[\s-]*marketing\b|\bconsumer[\s-]*neuroscience\b|\bneuro[\s-]*ergonomics?\b|\baffective[\s-]*computing\b|\bemotion[\s-]*recognition\b|\bcognitive[\s-]*(?:load|state|workload)\b|\bbrain[\s-]*computer[\s-]*interfaces?\b|\bneuro[\s-]*technolog\w+|\bbio[\s-]*signals?\b|\bphysiological[\s-]*signals?\b|\belectrodermal\b|\bgalvanic[\s-]*skin\b|\bdry[\s-]*electrodes?\b|\bwearable[\s-]*(?:EEG|sensors?)\b", False, False)],
    "sensoristica": [(r"\bbiosensor\w*", False, False),
                     (r"\bwearables?\b", True, False),
                     (r"\bsensoristica\b|\bsensors?\b|\bsensori\b|\bchemical[\s-]*sensors?\b|\bsensori[\s-]*chimici\b|\bsensor[\s-]*arrays?\b|\barray[\s-]*di[\s-]*sensori\b", True, True)],
    "lab_on_chip": [(r"\blab[\s-]*on[\s-]*(?:a[\s-]*)?chip\b|\bpoint[\s-]*of[\s-]*care\b", False, False)],
    "organ_on_chip": [(r"\borgans?[\s-]*on[\s-]*(?:a[\s-]*)?chips?\b|\b(?:tumou?rs?|cancer|disease|gut|lung|liver|heart|brain|kidney|body|human|muscle|skeletal[\s-]*muscle)[\s-]*on[\s-]*(?:a[\s-]*)?chips?\b|\bmicrophysiological\b|\bsarcopeni\w*|\borganoid\w*", False, False)],
    "microfluidica": [(r"\bmicro[\s-]*fluidic\w*|\bmicrofluidica\b", False, False)],
    "elettrodi_mea_grafene": [(r"\blaser[\s-]*induced[\s-]*graphene\b|\bgraphene[\s-]*(?:based[\s-]*)?(?:electrodes?|sensors?)\b|\bgrafene[\s-]*indotto\b|\belettrodi[\s-]*(?:in[\s-]*)?grafene\b|\bmulti[\s-]*electrode[\s-]*arrays?\b|\bmicro[\s-]*electrode[\s-]*arrays?\b|\barray[\s-]*di[\s-]*microelettrodi\b|\bbio[\s-]*electronics?\b|\bbio[\s-]*elettronica\b", False, False)],
    "biologia_computazionale": [(r"\bcomputational[\s-]*biology\b|\bbiologia[\s-]*computazionale\b|\bmulti[\s-]*omics?\b|\bbio[\s-]*informatics?\b|\bbioinformatica\b|\bprecision[\s-]*(?:medicine|oncology)\b|\bpersonali[sz]ed[\s-]*(?:medicine|therap\w+)\b|\bmedicina[\s-]*(?:personalizzata|di[\s-]*precisione)\b", False, False)],
    "oncologia_immunoterapia": [(r"\bimmuno[\s-]*(?:therap\w+|oncology)\b|\bimmunoterapi\w+|\bcolorectal\b|\bcolon[\s-]*retto\b|\bcancer\b|\boncolog\w+|\bmicrobio(?:ta|me)\b|\btumou?rs?\b|\btumor[ei]\b", False, True)],
    "tossicita_farmaci": [(r"\bcardio[\s-]*tox\w*|\bcardiotossic\w*|\bdrug[\s-]*induced[\s-]*(?:toxicity|injury|tossicit\w+)|\bnew[\s-]*approach[\s-]*methodolog\w*|\bin[\s-]*vitro[\s-]*toxic\w*|\btossicologia[\s-]*in[\s-]*vitro\b", False, False),
                          (r"\bcytotox\w*|\bcitotossic\w*|\bbioactive\b|\bbioattiv\w*|\bnatural[\s-]*compounds?\b", False, True)],
    "algoritmi_bioispirati": [(r"\b(?:bio|nature)[\s-]*inspired[\s-]*(?:algorithms?|optimi[sz]ation|computing)\b|\balgoritmi[\s-]*(?:bio|natura)[\s-]*ispirati\b", False, False)],
    "tecnologie_emergenti_biomedicali": [(r"\bmedical[\s-]*devices?\b|\bdispositiv\w*[\s-]*medic\w*|\bin[\s-]*vitro[\s-]*diagnostic\w*|\bdiagnostica[\s-]*in[\s-]*vitro\b|\bmedtech\b|\bscienze\s+della\s+vita\b|\blife\s+sciences?\b|\btime[\s-]*lapse[\s-]*(?:micro|imaging)\w*|\bmicroscopia[\s-]*time[\s-]*lapse\b", False, True)],
}


# Ambito applicativo del bando: serve a separare la salute dagli altri settori in cui il gruppo può lavorare.
TEMI_SALUTE = {"lab_on_chip", "organ_on_chip", "microfluidica", "elettrodi_mea_grafene",
               "biologia_computazionale", "oncologia_immunoterapia", "tossicita_farmaci"}  # temi specificamente biomedici (non ML generico)
AMBITI = {
    "salute": SALUTE,
    "agrifood": re.compile(r"\bagricultur\w+|\bagri[\s-]*food\b|\bagroaliment\w+|\bfood\b|\balimentar\w+|\bfarming\b|\bcrops?\b|\bviticultur\w+|\baquaculture\b|\bfisher(?:y|ies)\b|\bpesca\b|\bagricolt\w+", re.I),
    "ambiente_acqua": re.compile(r"\bwater\b|\bacqua\b|\bacque\b|\bidric\w+|\bambient\w+|\benvironmental\b|\bclimate\b|\bclima\w*|\bbiodiversit\w+|\binquinament\w+|\bpollution\b|\bmarine\b|\bocean\w*|\bcircular[\s-]*economy\b|\beconomia[\s-]*circolare\b|\bwaste\b|\brifiuti\b", re.I),
    "patrimonio_culturale": re.compile(r"\bcultural[\s-]*heritage\b|\bpatrimonio[\s-]*cultural\w+|\bbeni[\s-]*cultural\w+|\barchaeolog\w+|\barcheolog\w+|\bmuseum\w*|\bmusei\b|\bmuseo\b", re.I),
    "edilizia_infrastrutture": re.compile(r"\bconstruction\b|\bedilizia\b|\bbuilt[\s-]*environment\b|\bbuilding[\s-]*(?:sector|renovation|stock|construction|materials?)\b|\bedific\w+|\binfrastruttur\w+|\bcivil[\s-]*engineering\b|\burbanistic\w+|\burban[\s-]*(?:planning|areas?|development)\b", re.I),
    "energia_mobilita": re.compile(r"\benerg(?:y|ia)\b|\bhydrogen\b|\bidrogeno\b|\bbatter(?:y|ies|ie)\b|\bmobilit\w+|\bautomotive\b|\btransport\w*|\btrasport\w+|\bsmart[\s-]*grid\b", re.I),
    "industria_elettronica": re.compile(r"\bmanufactur\w+|\bmanifattur\w+|\bindustry[\s-]*4\.0\b|\bindustria[\s-]*4\.0\b|\brobot\w*|\bsemiconductor\w*|\bsemiconduttor\w+|\bmicro[\s-]*electronic\w*|\bmicroelettronic\w+|\bphotonic\w*|\bfotonic\w+|\baerospace\b|\bspace[\s-]*(?:technolog\w+|sector|missions?)\b|\bspazi\w+", re.I),
}


def ambiti(titolo, testo, temi):
    """Un ambito è attribuito se compare nel titolo o almeno 3 volte nel testo (la salute anche dai temi trovati)."""
    out = []
    for nome, pat in AMBITI.items():
        n = len(pat.findall(testo))
        if pat.search(titolo) or n >= 3 or (nome == "salute" and TEMI_SALUTE & set(temi)):
            out.append(nome)
    return out


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
            isolata = (serve_salute or tema in ISOLABILI) and len(ms) < 2 and not in_titolo and len(fonte) >= 600
            deb = (debole and not (in_titolo and tema in PROMUOVI_IN_TITOLO and SALUTE.search(titolo))) or isolata
            (deboli if deb else forti).append(tema)
            evidenze.append(testo[max(0, m.start() - 60): m.end() + 60])
            nel_titolo = nel_titolo or in_titolo
            break
    evidenze = [e for e in evidenze if e in testo][:3]
    solo_nuovi = bool(forti) and set(forti) <= NUOVI  # ogni evidenza è un frammento reale del testo
    temi = forti + deboli
    if forti:
        p = min(10, 4 + 2 * len(forti) + (1 if deboli else 0) + (1 if nel_titolo else 0))
        mot = "Trovati termini dei temi: " + ", ".join(temi) + ". Corrispondenza lessicale, non un giudizio sul contenuto."
        if set(forti) <= NUOVI and SSH.search(testo) and not (TEMI_SALUTE & set(temi)):
            p = min(p, 5)
            mot += " Bando di scienze sociali e umanistiche in cui l'IA è l'oggetto di studio e non lo strumento: punteggio limitato a 5."
        if solo_nuovi and bando.get("canale") != "Europa" and not RICERCA_HINT.search(testo):
            p = min(p, 5)
            mot += " Tema IA/imaging senza segni di ricerca nel testo (bando probabilmente per imprese): punteggio limitato a 5."
    elif deboli:
        p = min(5, 3 + len(deboli))
        mot = ("Solo termini generici o menzioni isolate (" + ", ".join(deboli) + "), che possono comparire di passaggio: "
               "corrispondenza debole, punteggio limitato a 5.")
    elif bando.get("ente") == "MIMIT" and GENERICO.search(testo):
        g = GENERICO.search(testo)
        p, temi = 4, ["ricerca_industriale_generica"]
        evidenze = [testo[max(0, g.start() - 60): g.end() + 60]]
        mot = ("Misura di ricerca e sviluppo per imprese, tema non specifico: l'università può essere partner di ricerca. "
               "Punteggio fisso, da valutare a mano.")
    elif bando.get("ente") == "MUR" and re.match(r"\s*bando\s+(prin|fis|synergy)", bando.get("titolo", ""), re.I):
        p, temi = 6, ["bando_generalista_ricerca"]
        evidenze = []
        mot = ("Bando di ricerca aperto a tutti i settori (PRIN/FIS/Synergy): il tema del gruppo non compare nel testo, "
               "ma il gruppo può candidarsi. Punteggio fisso, da valutare a mano.")
    elif bando.get("ente", "").startswith("Regione Lazio (Salute") and SANITA_RICERCA.search(testo):
        g = SANITA_RICERCA.search(testo)
        p, temi = 6, ["ricerca_biomedica_sanitaria"]
        evidenze = [testo[max(0, g.start() - 60): g.end() + 60]]
        mot = ("Avviso regionale per la ricerca sanitaria/biomedica (spesso rivolto a enti del SSN, con l'università come partner). "
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
            "destinatari": {"valore": "non_indicato", "citazione": None}, "rubrica": VERSIONE,
            "ambiti": ambiti(titolo, testo, temi)}


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
