"""
Blocchi di testo task-specifici per NASA Moon Survival, iniettati dal core
moderation nello scheletro del system prompt LLM.

I blocchi includono lo scenario lunare e le 6 ground rules procedurali
di Hall & Watson (1970) che il moderatore AI deve far rispettare.
"""

# Le 6 ground rules (tradotte in italiano) da Hall & Watson (1970),
# riprese dall'Experimental Briefing di MTa Learning.
GROUND_RULES = """1. Evitate di insistere sulla vostra posizione. Presentate le vostre ragioni in modo chiaro e logico, ma considerate seriamente le reazioni del gruppo.
2. Evitate situazioni di stallo "io vinco, tu perdi". Quando c'e un'impasse, cercate l'alternativa piu accettabile per tutti.
3. Non cambiate idea solo per evitare il conflitto. Resistete alle pressioni che non hanno basi logiche. Cercate la flessibilita ragionata, non la resa.
4. Evitate tecniche che riducono il conflitto come il voto a maggioranza, la media, il compromesso o il lancio della moneta. Trattate i disaccordi come segnale che qualcuno ha informazioni utili da condividere.
5. Considerate le differenze di opinione naturali e utili, non un ostacolo. Piu idee emergono, piu risorse ha il gruppo.
6. Diffidate dell'accordo immediato. Esplorate le ragioni dietro un accordo apparente: assicuratevi che le persone siano arrivate alla stessa conclusione per le stesse ragioni o per ragioni complementari."""


SCENARIO_BLOCK_NORMAL = f"""## Scenario
I partecipanti stanno affrontando la NASA Moon Survival Challenge. Sono un equipaggio di astronauti il cui modulo lunare si e schiantato a circa 300 km dalla base sulla superficie illuminata della Luna. Devono classificare 15 oggetti in ordine di importanza per la sopravvivenza e il raggiungimento della base. L'obiettivo e raggiungere un consenso di gruppo su un unico ranking condiviso.

## Regole procedurali per il consenso
Il moderatore deve incoraggiare il rispetto di queste regole durante la discussione:
{GROUND_RULES}"""


SCENARIO_BLOCK_FORCED_CONCLUSION = """## Scenario
I partecipanti hanno affrontato la NASA Moon Survival Challenge. Al termine della sessione l'host deve confermare il ranking finale dei 15 oggetti nell'interfaccia. Il ranking deve riflettere il consenso raggiunto dal gruppo durante la discussione."""
