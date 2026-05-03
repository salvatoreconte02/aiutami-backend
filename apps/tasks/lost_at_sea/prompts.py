"""
Blocchi di testo task-specifici per Lost at Sea, iniettati dal core
moderation nello scheletro del system prompt LLM.

I blocchi includono lo scenario oceanico e le 6 ground rules procedurali
di Hall & Watson (1970). Le 6 rules complete vanno nell'intro TTS ai
partecipanti (informazione totale); il system prompt LLM riceve solo
il sottoinsieme che il moderatore enforces a runtime (rules 2, 4, 5 —
quelle con marker linguistici puntuali, vedi Feature 2.9).

Versioni IT/EN parallele per il system prompt. GROUND_RULES (intro TTS)
resta solo in italiano: l'intro non e' attualmente parametrizzata e va in
TTS ai partecipanti italiani.
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


# --- Italian: system prompt blocks ---

GROUND_RULES_ENFORCED_IT = """2. Evitate situazioni di stallo "io vinco, tu perdi". Quando c'e un'impasse, cercate l'alternativa piu accettabile per tutti.
4. Evitate tecniche che riducono il conflitto come il voto a maggioranza, la media, il compromesso o il lancio della moneta. Trattate i disaccordi come segnale che qualcuno ha informazioni utili da condividere.
5. Considerate le differenze di opinione naturali e utili, non un ostacolo. Piu idee emergono, piu risorse ha il gruppo."""


SCENARIO_BLOCK_NORMAL_IT = f"""## Scenario
I partecipanti stanno affrontando la Lost at Sea Survival Challenge. Sono naufraghi il cui yacht è affondato nel mezzo dell'Oceano Atlantico, a centinaia di miglia dalla terra più vicina. Hanno salvato 15 oggetti e devono classificarli in ordine di importanza per la sopravvivenza in attesa dei soccorsi. L'obiettivo è raggiungere un consenso di gruppo su un unico ranking condiviso.

## Regole procedurali per il consenso
Il moderatore deve incoraggiare il rispetto di queste regole durante la discussione (numerazione originale di Hall & Watson 1970, sottoinsieme enforced):
{GROUND_RULES_ENFORCED_IT}"""


SCENARIO_BLOCK_FORCED_CONCLUSION_IT = """## Scenario
I partecipanti hanno affrontato la Lost at Sea Survival Challenge. Al termine della sessione l'host deve confermare il ranking finale dei 15 oggetti nell'interfaccia. Il ranking deve riflettere il consenso raggiunto dal gruppo durante la discussione."""


# --- English: system prompt blocks ---

GROUND_RULES_ENFORCED_EN = """2. Avoid "I win, you lose" deadlocks. When there's an impasse, look for the alternative most acceptable to everyone.
4. Avoid conflict-reducing techniques such as majority vote, averaging, compromise or coin flips. Treat disagreements as a signal that someone holds useful information worth sharing.
5. Treat differences of opinion as natural and useful, not an obstacle. The more ideas emerge, the more resources the group has."""


SCENARIO_BLOCK_NORMAL_EN = f"""## Scenario
The participants are tackling the Lost at Sea Survival Challenge. They are castaways whose yacht has sunk in the middle of the Atlantic Ocean, hundreds of miles from the nearest land. They've salvaged 15 items and must rank them in order of importance for survival while awaiting rescue. The goal is to reach group consensus on a single shared ranking.

## Procedural rules for consensus
The moderator must encourage adherence to these rules during the discussion (original numbering from Hall & Watson 1970, enforced subset):
{GROUND_RULES_ENFORCED_EN}"""


SCENARIO_BLOCK_FORCED_CONCLUSION_EN = """## Scenario
The participants have tackled the Lost at Sea Survival Challenge. At the end of the session the host must confirm the final ranking of the 15 items in the interface. The ranking should reflect the consensus reached by the group during the discussion."""


# --- Backward-compat aliases (default Italian) ---

GROUND_RULES_ENFORCED = GROUND_RULES_ENFORCED_IT
SCENARIO_BLOCK_NORMAL = SCENARIO_BLOCK_NORMAL_IT
SCENARIO_BLOCK_FORCED_CONCLUSION = SCENARIO_BLOCK_FORCED_CONCLUSION_IT
