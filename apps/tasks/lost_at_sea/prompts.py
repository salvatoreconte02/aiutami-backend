"""
Blocchi di testo task-specifici per Lost at Sea, iniettati dal core
moderation nello scheletro del system prompt LLM.

I blocchi includono lo scenario oceanico e le 6 ground rules procedurali
di Hall & Watson (1970). Le 6 rules complete vanno nell'intro TTS ai
partecipanti (informazione totale); il system prompt LLM riceve solo
il sottoinsieme che il moderatore enforces a runtime (rules 2, 4, 5 —
quelle con marker linguistici puntuali, vedi Feature 2.9).
"""

# Le 6 ground rules (tradotte in italiano) da Hall & Watson (1970),
# riprese dall'Experimental Briefing di MTa Learning.
# USATE NELL'INTRO TTS AI PARTECIPANTI (intro_message_tail).
GROUND_RULES = """1. Evitate di insistere sulla vostra posizione. Presentate le vostre ragioni in modo chiaro e logico, ma considerate seriamente le reazioni del gruppo.
2. Evitate situazioni di stallo "io vinco, tu perdi". Quando c'e un'impasse, cercate l'alternativa piu accettabile per tutti.
3. Non cambiate idea solo per evitare il conflitto. Resistete alle pressioni che non hanno basi logiche. Cercate la flessibilita ragionata, non la resa.
4. Evitate tecniche che riducono il conflitto come il voto a maggioranza, la media, il compromesso o il lancio della moneta. Trattate i disaccordi come segnale che qualcuno ha informazioni utili da condividere.
5. Considerate le differenze di opinione naturali e utili, non un ostacolo. Piu idee emergono, piu risorse ha il gruppo.
6. Diffidate dell'accordo immediato. Esplorate le ragioni dietro un accordo apparente: assicuratevi che le persone siano arrivate alla stessa conclusione per le stesse ragioni o per ragioni complementari."""


# Sottoinsieme enforced a runtime (rules 2, 4, 5). Numerazione H&W
# preservata per traceability vs paper. USATE NEL SYSTEM PROMPT LLM.
GROUND_RULES_ENFORCED = """2. Evitate situazioni di stallo "io vinco, tu perdi". Quando c'e un'impasse, cercate l'alternativa piu accettabile per tutti.
4. Evitate tecniche che riducono il conflitto come il voto a maggioranza, la media, il compromesso o il lancio della moneta. Trattate i disaccordi come segnale che qualcuno ha informazioni utili da condividere.
5. Considerate le differenze di opinione naturali e utili, non un ostacolo. Piu idee emergono, piu risorse ha il gruppo."""


SCENARIO_BLOCK_NORMAL = f"""## Scenario
I partecipanti stanno affrontando la Lost at Sea Survival Challenge. Sono naufraghi il cui yacht è affondato nel mezzo dell'Oceano Atlantico, a centinaia di miglia dalla terra più vicina. Hanno salvato 15 oggetti e devono classificarli in ordine di importanza per la sopravvivenza in attesa dei soccorsi. L'obiettivo è raggiungere un consenso di gruppo su un unico ranking condiviso.

## Regole procedurali per il consenso
Il moderatore deve incoraggiare il rispetto di queste regole durante la discussione (numerazione originale di Hall & Watson 1970, sottoinsieme enforced):
{GROUND_RULES_ENFORCED}"""


SCENARIO_BLOCK_FORCED_CONCLUSION = """## Scenario
I partecipanti hanno affrontato la Lost at Sea Survival Challenge. Al termine della sessione l'host deve confermare il ranking finale dei 15 oggetti nell'interfaccia. Il ranking deve riflettere il consenso raggiunto dal gruppo durante la discussione."""
